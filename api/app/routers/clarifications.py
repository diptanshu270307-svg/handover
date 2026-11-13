from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    AuditLog,
    Claim,
    ClaimReview,
    Clarification,
    Conflict,
    ConflictStatus,
    EvidenceState,
    Project,
    ReviewAction,
    User,
)
from app.permissions import claim_access_filter

router = APIRouter(prefix="/clarifications", tags=["clarifications"])


class AnswerClarificationRequest(BaseModel):
    answer_text: str = Field(..., min_length=2)


def _serialize(c: Clarification, user_map: dict[uuid.UUID, User]) -> dict:
    asked = user_map.get(c.asked_to_user_id)
    answered = user_map.get(c.answered_by_id) if c.answered_by_id else None
    return {
        "id": str(c.id),
        "project_id": str(c.project_id),
        "target_type": c.target_type,
        "claim_id": str(c.claim_id) if c.claim_id else None,
        "conflict_id": str(c.conflict_id) if c.conflict_id else None,
        "question": c.question,
        "asked_to": {"id": str(asked.id), "name": asked.name, "role": asked.role.value} if asked else None,
        "answer_text": c.answer_text,
        "answered_by": (
            {"id": str(answered.id), "name": answered.name, "role": answered.role.value}
            if answered
            else None
        ),
        "answered_at": c.answered_at.isoformat() if c.answered_at else None,
        "status": c.status,
        "created_at": c.created_at.isoformat(),
    }


@router.get("")
def list_clarifications(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.scalars(
        select(Clarification)
        .where(Clarification.project_id == project_id)
        .order_by(Clarification.created_at.asc())
    ).all()
    user_map = {u.id: u for u in db.scalars(select(User)).all()}
    return {"count": len(rows), "clarifications": [_serialize(c, user_map) for c in rows]}


@router.post("/generate")
def generate_clarifications(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    existing = db.scalars(
        select(Clarification).where(Clarification.project_id == project_id)
    ).all()
    existing_claim_ids = {c.claim_id for c in existing if c.claim_id}
    existing_conflict_ids = {c.conflict_id for c in existing if c.conflict_id}

    created: list[Clarification] = []

    # 1. Targeted questions for open conflicts
    open_conflicts = db.scalars(
        select(Conflict).where(
            Conflict.project_id == project_id,
            Conflict.status == ConflictStatus.open,
        )
    ).all()
    for cf in open_conflicts:
        if cf.id in existing_conflict_ids:
            continue
        q = f"Conflict clarification ({cf.title}): Which source reflects the current production state, and why do the sources disagree?"
        cl = Clarification(
            project_id=project_id,
            target_type="conflict",
            conflict_id=cf.id,
            question=q,
            asked_to_user_id=project.departing_user_id,
            status="open",
        )
        db.add(cl)
        created.append(cl)

    # 2. Targeted questions for missing-evidence gaps
    missing_claims = db.scalars(
        select(Claim).where(
            Claim.project_id == project_id,
            Claim.evidence_state == EvidenceState.missing,
            claim_access_filter(current_user),
        )
    ).all()
    for mc in missing_claims:
        if mc.id in existing_claim_ids:
            continue
        q = f"Knowledge gap: {mc.text} Can you provide the rationale, decision context, or link to where this is documented?"
        cl = Clarification(
            project_id=project_id,
            target_type="gap",
            claim_id=mc.id,
            question=q,
            asked_to_user_id=project.departing_user_id,
            status="open",
        )
        db.add(cl)
        created.append(cl)

    db.flush()
    db.add(
        AuditLog(
            project_id=project_id,
            actor_id=current_user.id,
            action="clarifications_generated",
            entity_type="project",
            entity_id=project_id,
            details={"created_count": len(created)},
        )
    )
    db.commit()

    user_map = {u.id: u for u in db.scalars(select(User)).all()}
    return {"created_count": len(created), "clarifications": [_serialize(c, user_map) for c in created]}


@router.post("/{clarification_id}/answer")
def answer_clarification(
    clarification_id: uuid.UUID,
    payload: AnswerClarificationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cl = db.get(Clarification, clarification_id)
    if not cl:
        raise HTTPException(status_code=404, detail="Clarification not found")

    now = datetime.now(timezone.utc)
    answer = payload.answer_text.strip()
    cl.answer_text = answer
    cl.answered_by_id = current_user.id
    cl.answered_at = now
    cl.status = "answered"

    attributed = f"[Clarification by {current_user.name} ({current_user.role.value}) on {now.date().isoformat()}]: {answer}"

    # Link attributed answer to target claim or conflict
    if cl.claim_id:
        claim = db.get(Claim, cl.claim_id)
        if claim:
            claim.limitation_note = (
                f"{claim.limitation_note}\n{attributed}".strip()
                if claim.limitation_note
                else attributed
            )
            db.add(
                ClaimReview(
                    claim_id=claim.id,
                    reviewer_id=current_user.id,
                    action=ReviewAction.edit,
                    old_text=claim.text,
                    new_text=claim.text,
                    note=attributed,
                )
            )

    if cl.conflict_id:
        conflict = db.get(Conflict, cl.conflict_id)
        if conflict:
            conflict.resolution_note = (
                f"{conflict.resolution_note}\n{attributed}".strip()
                if conflict.resolution_note
                else attributed
            )

    db.add(
        AuditLog(
            project_id=cl.project_id,
            actor_id=current_user.id,
            action="clarification_answered",
            entity_type="clarification",
            entity_id=cl.id,
            details={"target_type": cl.target_type, "answered_by": current_user.name},
        )
    )
    db.commit()

    user_map = {u.id: u for u in db.scalars(select(User)).all()}
    return _serialize(cl, user_map)

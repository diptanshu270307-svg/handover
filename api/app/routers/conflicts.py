from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.extraction.conflict_detector import detect_conflicts_and_gaps
from app.models import (
    AuditLog,
    Claim,
    ClaimEvidence,
    ClaimReview,
    Conflict,
    ConflictStatus,
    EvidenceState,
    Responsibility,
    ResponsibilityStatus,
    ReviewAction,
    Source,
    SourceChunk,
    User,
    UserRole,
)
from app.permissions import can_access_record, claim_access_filter

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


class DetectConflictsRequest(BaseModel):
    project_id: uuid.UUID
    handover_version_id: uuid.UUID | None = None
    use_llm: bool = False


class ResolveConflictRequest(BaseModel):
    winning_claim_id: uuid.UUID
    resolution_note: str = Field(..., min_length=3, description="Required explanation for resolving this conflict")


@router.get("")
def list_conflicts(
    project_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Conflict)
    if project_id:
        stmt = stmt.where(Conflict.project_id == project_id)
    conflicts = db.scalars(stmt.order_by(Conflict.created_at.asc())).all()

    out = []
    for cf in conflicts:
        claims = db.scalars(
            select(Claim).where(Claim.id.in_(cf.claim_ids), claim_access_filter(current_user))
        ).all()
        if not claims:
            continue

        sides = []
        for cl in claims:
            ev_rows = db.execute(
                select(ClaimEvidence, SourceChunk, Source)
                .join(SourceChunk, ClaimEvidence.chunk_id == SourceChunk.id)
                .join(Source, SourceChunk.source_id == Source.id)
                .where(ClaimEvidence.claim_id == cl.id)
            ).all()

            passages = []
            for ev, chunk, src in ev_rows:
                if not can_access_record(current_user, src.allowed_roles, src.allowed_user_ids):
                    continue
                passages.append(
                    {
                        "source_id": str(src.id),
                        "source_title": src.title,
                        "source_type": src.type.value,
                        "source_uri": src.uri,
                        "version_sha": src.version_sha,
                        "source_date": src.source_date.isoformat() if src.source_date else None,
                        "chunk_id": str(chunk.id),
                        "quote_span": ev.quote_span,
                    }
                )

            sides.append(
                {
                    "claim_id": str(cl.id),
                    "text": cl.text,
                    "type": cl.type.value,
                    "evidence_state": cl.evidence_state.value,
                    "passages": passages,
                }
            )

        out.append(
            {
                "id": str(cf.id),
                "project_id": str(cf.project_id),
                "title": cf.title,
                "status": cf.status.value,
                "winning_claim_id": str(cf.winning_claim_id) if cf.winning_claim_id else None,
                "resolution_note": cf.resolution_note,
                "resolved_by": str(cf.resolved_by) if cf.resolved_by else None,
                "resolved_at": cf.resolved_at.isoformat() if cf.resolved_at else None,
                "sides": sides,
            }
        )

    return {"count": len(out), "conflicts": out}


@router.get("/gaps")
def list_gaps(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    missing_claims = db.scalars(
        select(Claim).where(
            Claim.project_id == project_id,
            Claim.evidence_state == EvidenceState.missing,
            claim_access_filter(current_user),
        )
    ).all()

    unassigned_resps = db.scalars(
        select(Responsibility).where(
            Responsibility.project_id == project_id,
            Responsibility.status == ResponsibilityStatus.unassigned,
        )
    ).all()

    return {
        "missing_claims": [
            {
                "id": str(c.id),
                "type": c.type.value,
                "text": c.text,
                "evidence_state": c.evidence_state.value,
                "limitation_note": c.limitation_note,
            }
            for c in missing_claims
        ],
        "unassigned_responsibilities": [
            {
                "id": str(r.id),
                "item": r.item,
                "description": r.description,
                "status": r.status.value,
            }
            for r in unassigned_resps
        ],
    }


@router.post("/detect")
def trigger_conflict_detection(
    payload: DetectConflictsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    summary = detect_conflicts_and_gaps(
        db=db,
        project_id=payload.project_id,
        handover_version_id=payload.handover_version_id,
        use_llm=payload.use_llm,
    )
    db.add(
        AuditLog(
            project_id=payload.project_id,
            actor_id=current_user.id,
            action="conflicts_detected",
            entity_type="project",
            entity_id=payload.project_id,
            details=summary,
        )
    )
    db.commit()
    return summary


@router.post("/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: uuid.UUID,
    payload: ResolveConflictRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.reviewer:
        raise HTTPException(status_code=403, detail="Only a reviewer can resolve conflicts.")

    conflict = db.get(Conflict, conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict not found")

    if payload.winning_claim_id not in conflict.claim_ids:
        raise HTTPException(
            status_code=422,
            detail="winning_claim_id must be one of the claims in this conflict.",
        )

    explanation = payload.resolution_note.strip()
    if not explanation:
        raise HTTPException(status_code=422, detail="resolution_note explanation is required.")

    now = datetime.now(timezone.utc)
    conflict.status = ConflictStatus.resolved
    conflict.winning_claim_id = payload.winning_claim_id
    conflict.resolution_note = explanation
    conflict.resolved_by = current_user.id
    conflict.resolved_at = now

    claims = db.scalars(select(Claim).where(Claim.id.in_(conflict.claim_ids))).all()
    superseded_ids: list[str] = []
    for cl in claims:
        old_state = cl.evidence_state.value
        if cl.id == payload.winning_claim_id:
            cl.evidence_state = EvidenceState.human_confirmed
            db.add(
                ClaimReview(
                    claim_id=cl.id,
                    reviewer_id=current_user.id,
                    action=ReviewAction.resolve_conflict,
                    old_text=cl.text,
                    new_text=cl.text,
                    note=f"Confirmed as winning claim (was {old_state}): {explanation}",
                )
            )
        else:
            cl.evidence_state = EvidenceState.superseded
            superseded_ids.append(str(cl.id))
            db.add(
                ClaimReview(
                    claim_id=cl.id,
                    reviewer_id=current_user.id,
                    action=ReviewAction.mark_superseded,
                    old_text=cl.text,
                    new_text=cl.text,
                    note=f"Marked superseded in favor of {payload.winning_claim_id}: {explanation}",
                )
            )

    db.add(
        AuditLog(
            project_id=conflict.project_id,
            actor_id=current_user.id,
            action="conflict_resolved",
            entity_type="conflict",
            entity_id=conflict.id,
            details={
                "winning_claim_id": str(payload.winning_claim_id),
                "superseded_claim_ids": superseded_ids,
                "resolution_note": explanation,
            },
        )
    )
    db.commit()

    return {
        "id": str(conflict.id),
        "status": conflict.status.value,
        "winning_claim_id": str(conflict.winning_claim_id),
        "superseded_claim_ids": superseded_ids,
        "resolution_note": conflict.resolution_note,
        "resolved_by": str(conflict.resolved_by),
        "resolved_at": conflict.resolved_at.isoformat(),
    }

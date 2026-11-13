from datetime import datetime, timezone
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    AuditLog,
    Claim,
    Project,
    RehearsalResult,
    RehearsalTask,
    Responsibility,
    ResponsibilityStatus,
    SourceChunk,
    User,
    UserRole,
)
from app.permissions import chunk_access_filter, claim_access_filter

router = APIRouter(prefix="/projects/{project_id}/rehearsal", tags=["rehearsal"])


class ResponsibilityDecisionInput(BaseModel):
    responsibility_id: uuid.UUID
    decision: Literal["accept", "block"]
    note: str | None = None


class RehearsalSubmitRequest(BaseModel):
    rehearsal_task_id: uuid.UUID
    answer_text: str = Field(..., min_length=1)
    evidence_chunk_ids: list[uuid.UUID] = Field(default_factory=list)
    evidence_claim_ids: list[uuid.UUID] = Field(default_factory=list)
    gaps_hit: list[str] = Field(default_factory=list)
    duration_seconds: int | None = Field(default=None, ge=0)
    responsibility_decisions: list[ResponsibilityDecisionInput] = Field(default_factory=list)


@router.get("")
def get_rehearsal(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    tasks = db.scalars(
        select(RehearsalTask)
        .where(RehearsalTask.project_id == project_id)
        .order_by(RehearsalTask.task_order.asc())
    ).all()

    results = db.scalars(
        select(RehearsalResult)
        .where(RehearsalResult.project_id == project_id)
        .order_by(RehearsalResult.completed_at.desc())
    ).all()

    return {
        "project_id": str(project_id),
        "tasks": [
            {
                "id": str(t.id),
                "task_order": t.task_order,
                "title": t.title,
                "prompt": t.prompt,
                "expected_topic": t.expected_topic,
            }
            for t in tasks
        ],
        "results": [
            {
                "id": str(r.id),
                "rehearsal_task_id": str(r.rehearsal_task_id),
                "successor_id": str(r.successor_id),
                "answer_text": r.answer_text,
                "evidence_chunk_ids": [str(cid) for cid in r.evidence_chunk_ids],
                "evidence_claim_ids": [str(cid) for cid in r.evidence_claim_ids],
                "gaps_hit": r.gaps_hit,
                "duration_seconds": r.duration_seconds,
                "responsibility_decisions": r.responsibility_decisions,
                "passed": r.passed,
                "completed_at": r.completed_at.isoformat(),
            }
            for r in results
        ],
    }


@router.post("/submit")
def submit_rehearsal(
    project_id: uuid.UUID,
    payload: RehearsalSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.get(RehearsalTask, payload.rehearsal_task_id)
    if not task or task.project_id != project_id:
        raise HTTPException(status_code=404, detail="Rehearsal task not found")

    permitted_chunk_ids: list[uuid.UUID] = []
    if payload.evidence_chunk_ids:
        permitted_chunks = db.scalars(
            select(SourceChunk).where(
                SourceChunk.id.in_(payload.evidence_chunk_ids),
                chunk_access_filter(current_user),
            )
        ).all()
        permitted_chunk_ids = [c.id for c in permitted_chunks]
        if len(permitted_chunk_ids) != len(set(payload.evidence_chunk_ids)):
            raise HTTPException(status_code=403, detail="One or more cited chunks are not permitted.")

    permitted_claim_ids: list[uuid.UUID] = []
    if payload.evidence_claim_ids:
        permitted_claims = db.scalars(
            select(Claim).where(
                Claim.id.in_(payload.evidence_claim_ids),
                claim_access_filter(current_user),
            )
        ).all()
        permitted_claim_ids = [c.id for c in permitted_claims]
        if len(permitted_claim_ids) != len(set(payload.evidence_claim_ids)):
            raise HTTPException(status_code=403, detail="One or more cited claims are not permitted.")

    decisions_serialized: list[dict] = []
    gaps = list(payload.gaps_hit)
    for dec in payload.responsibility_decisions:
        resp = db.get(Responsibility, dec.responsibility_id)
        if not resp or resp.project_id != project_id:
            continue
        decisions_serialized.append(
            {
                "responsibility_id": str(resp.id),
                "item": resp.item,
                "decision": dec.decision,
                "note": dec.note,
            }
        )
        if (
            dec.decision == "accept"
            and current_user.role == UserRole.successor
            and resp.confirmed_owner_id == current_user.id
        ):
            resp.accepted_by_id = current_user.id
            resp.status = ResponsibilityStatus.accepted
        elif dec.decision == "block":
            gaps.append(f"Blocked responsibility '{resp.item}': {dec.note or 'No reason given'}")

    has_evidence = bool(permitted_chunk_ids or permitted_claim_ids)
    passed = bool(payload.answer_text.strip()) and has_evidence and not any(
        d["decision"] == "block" for d in decisions_serialized
    )

    result = RehearsalResult(
        rehearsal_task_id=task.id,
        project_id=project_id,
        successor_id=current_user.id,
        answer_text=payload.answer_text.strip(),
        evidence_chunk_ids=permitted_chunk_ids,
        evidence_claim_ids=permitted_claim_ids,
        gaps_hit=gaps,
        duration_seconds=payload.duration_seconds,
        responsibility_decisions=decisions_serialized,
        passed=passed,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(result)
    db.add(
        AuditLog(
            project_id=project_id,
            actor_id=current_user.id,
            action="rehearsal_submitted",
            entity_type="rehearsal_result",
            entity_id=result.id,
            details={
                "task_order": task.task_order,
                "passed": passed,
                "duration_seconds": payload.duration_seconds,
                "evidence_count": len(permitted_chunk_ids) + len(permitted_claim_ids),
                "gaps_hit": gaps,
                "responsibility_decisions": decisions_serialized,
            },
        )
    )
    db.commit()

    return {
        "id": str(result.id),
        "rehearsal_task_id": str(result.rehearsal_task_id),
        "successor_id": str(result.successor_id),
        "answer_text": result.answer_text,
        "evidence_chunk_ids": [str(c) for c in result.evidence_chunk_ids],
        "evidence_claim_ids": [str(c) for c in result.evidence_claim_ids],
        "gaps_hit": result.gaps_hit,
        "duration_seconds": result.duration_seconds,
        "responsibility_decisions": result.responsibility_decisions,
        "passed": result.passed,
        "completed_at": result.completed_at.isoformat(),
    }


@router.get("/readiness")
def get_readiness_summary(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Objective readiness summary computed strictly from task outcomes,
    evidence citations, gaps encountered, and responsibility decisions
    (no AI confidence score).
    """
    tasks = db.scalars(
        select(RehearsalTask).where(RehearsalTask.project_id == project_id)
    ).all()
    results = db.scalars(
        select(RehearsalResult)
        .where(RehearsalResult.project_id == project_id)
        .order_by(RehearsalResult.completed_at.desc())
    ).all()

    latest_by_task: dict[uuid.UUID, RehearsalResult] = {}
    for r in results:
        if r.rehearsal_task_id not in latest_by_task:
            latest_by_task[r.rehearsal_task_id] = r

    completed_results = list(latest_by_task.values())
    tasks_passed = sum(1 for r in completed_results if r.passed)
    total_duration = sum(r.duration_seconds or 0 for r in completed_results)
    all_gaps = [g for r in completed_results for g in (r.gaps_hit or [])]

    resps = db.scalars(
        select(Responsibility).where(Responsibility.project_id == project_id)
    ).all()
    accepted_count = sum(1 for r in resps if r.status == ResponsibilityStatus.accepted)
    blocked_count = sum(
        1
        for r in completed_results
        for d in (r.responsibility_decisions or [])
        if d.get("decision") == "block"
    )

    if len(completed_results) == 0:
        status = "not_started"
    elif len(completed_results) == len(tasks) and tasks_passed == len(tasks) and blocked_count == 0:
        status = "ready"
    else:
        status = "needs_followup"

    return {
        "project_id": str(project_id),
        "readiness_status": status,
        "tasks_total": len(tasks),
        "tasks_completed": len(completed_results),
        "tasks_passed": tasks_passed,
        "total_duration_seconds": total_duration,
        "gaps_encountered": all_gaps,
        "responsibilities_total": len(resps),
        "responsibilities_accepted": accepted_count,
        "responsibilities_blocked": blocked_count,
    }

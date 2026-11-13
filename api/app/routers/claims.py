from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    AuditLog,
    Claim,
    ClaimReview,
    EvidenceState,
    HandoverStatus,
    HandoverVersion,
    ReviewAction,
    User,
    UserRole,
)

router = APIRouter(prefix="/claims", tags=["claims"])


class ClaimReviewRequest(BaseModel):
    action: Literal["confirm", "edit", "reject", "mark_superseded", "flag_missing", "add_limitation"]
    new_text: str | None = None
    note: str | None = None
    limitation_note: str | None = None


@router.post("/{claim_id}/review")
def review_claim(
    claim_id: uuid.UUID,
    payload: ClaimReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.reviewer:
        raise HTTPException(status_code=403, detail="Only a reviewer can review claims.")

    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.handover_version_id:
        hv = db.get(HandoverVersion, claim.handover_version_id)
        if hv and hv.status == HandoverStatus.approved:
            raise HTTPException(
                status_code=409,
                detail="Cannot modify claims on an approved (immutable) handover version.",
            )

    old_text = claim.text
    new_text = claim.text
    db_action: ReviewAction

    if payload.action == "edit":
        if not payload.new_text or not payload.new_text.strip():
            raise HTTPException(status_code=422, detail="new_text is required for edit action.")
        new_text = payload.new_text.strip()
        claim.text = new_text
        claim.evidence_state = EvidenceState.human_confirmed
        db_action = ReviewAction.edit
    elif payload.action == "confirm":
        claim.evidence_state = EvidenceState.human_confirmed
        db_action = ReviewAction.confirm
    elif payload.action in ("reject", "mark_superseded"):
        claim.evidence_state = EvidenceState.superseded
        db_action = ReviewAction.mark_superseded
    elif payload.action == "flag_missing":
        claim.evidence_state = EvidenceState.missing
        if payload.limitation_note or payload.note:
            claim.limitation_note = (payload.limitation_note or payload.note or "").strip()
        db_action = ReviewAction.flag_missing
    elif payload.action == "add_limitation":
        lim = (payload.limitation_note or payload.note or "").strip()
        if not lim:
            raise HTTPException(status_code=422, detail="limitation_note is required.")
        claim.limitation_note = lim
        db_action = ReviewAction.flag_missing if claim.evidence_state == EvidenceState.missing else ReviewAction.edit
    else:
        raise HTTPException(status_code=422, detail=f"Unsupported review action: {payload.action}")

    # Re-reviewing clears stale flag
    if payload.action in ("confirm", "edit", "reject", "mark_superseded", "flag_missing"):
        claim.is_stale = False
        claim.stale_reason = None

    review = ClaimReview(
        claim_id=claim.id,
        reviewer_id=current_user.id,
        action=db_action,
        old_text=old_text,
        new_text=new_text,
        note=payload.note or payload.limitation_note,
    )
    db.add(review)
    db.add(
        AuditLog(
            project_id=claim.project_id,
            actor_id=current_user.id,
            action="claim_reviewed",
            entity_type="claim",
            entity_id=claim.id,
            details={
                "review_action": payload.action,
                "evidence_state": claim.evidence_state.value,
            },
        )
    )
    db.commit()

    return {
        "claim_id": str(claim.id),
        "action": payload.action,
        "text": claim.text,
        "old_text": old_text,
        "new_text": new_text,
        "evidence_state": claim.evidence_state.value,
        "limitation_note": claim.limitation_note,
        "review_id": str(review.id),
    }

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.extraction.conflict_detector import detect_conflicts_and_gaps
from app.extraction.llm_client import PermittedChunk, extract_claims_from_chunks
from app.extraction.validator import validate_extracted_claims
from app.models import (
    AuditLog,
    Claim,
    ClaimEvidence,
    ClaimReview,
    ClaimType,
    Conflict,
    ConflictStatus,
    HandoverStatus,
    HandoverVersion,
    Project,
    Receipt,
    Source,
    SourceChunk,
    User,
    UserRole,
)
from app.permissions import (
    can_access_record,
    chunk_access_filter,
    claim_access_filter,
    redact_evidence_if_denied,
    source_access_filter,
)

router = APIRouter(prefix="/handovers", tags=["handovers"])


class GenerateHandoverRequest(BaseModel):
    project_id: uuid.UUID
    successor_id: uuid.UUID | None = None
    use_mock: bool | None = None


class ApproveHandoverRequest(BaseModel):
    summary_notes: str | None = None


class AcknowledgeHandoverRequest(BaseModel):
    notes: str | None = None


def retrieve_permitted_chunks(
    db: Session,
    project_id: uuid.UUID,
    target_user: User,
) -> list[PermittedChunk]:
    """
    Enforce access BEFORE retrieval and BEFORE sending anything to the LLM.
    Only returns chunks whose Source AND SourceChunk policies permit `target_user`.
    """
    rows = db.execute(
        select(SourceChunk, Source)
        .join(Source, SourceChunk.source_id == Source.id)
        .where(
            SourceChunk.project_id == project_id,
            source_access_filter(target_user),
            chunk_access_filter(target_user),
        )
        .order_by(Source.source_date.asc().nulls_last(), SourceChunk.chunk_index.asc())
    ).all()

    return [
        PermittedChunk(
            chunk_id=str(chunk.id),
            source_id=str(source.id),
            source_title=source.title,
            source_type=source.type.value,
            source_date=source.source_date.isoformat() if source.source_date else None,
            version_sha=source.version_sha,
            text=chunk.text,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
        )
        for chunk, source in rows
    ]


def _serialize_handover(db: Session, handover: HandoverVersion, current_user: User) -> dict:
    # Filter claims by caller's permissions (approval never grants extra source access)
    claims = db.scalars(
        select(Claim)
        .where(
            Claim.project_id == handover.project_id,
            (Claim.handover_version_id == handover.id) | (Claim.handover_version_id.is_(None)),
            claim_access_filter(current_user),
        )
        .order_by(Claim.created_at.asc())
    ).all()

    claims_out = []
    for cl in claims:
        ev_rows = db.execute(
            select(ClaimEvidence, SourceChunk, Source)
            .join(SourceChunk, ClaimEvidence.chunk_id == SourceChunk.id)
            .join(Source, SourceChunk.source_id == Source.id)
            .where(ClaimEvidence.claim_id == cl.id)
        ).all()

        evidence_out = []
        for ev, chunk, src in ev_rows:
            full_payload = {
                "restricted": False,
                "id": str(ev.id),
                "chunk_id": str(chunk.id),
                "source_id": str(src.id),
                "source_title": src.title,
                "source_type": src.type.value,
                "source_uri": src.uri,
                "version_sha": src.version_sha,
                "source_date": src.source_date.isoformat() if src.source_date else None,
                "quote_span": ev.quote_span,
                "quote_start_offset": ev.quote_start_offset,
                "quote_end_offset": ev.quote_end_offset,
                "stance": ev.stance.value,
            }
            evidence_out.append(redact_evidence_if_denied(current_user, src, chunk, full_payload))

        reviews = db.scalars(
            select(ClaimReview)
            .where(ClaimReview.claim_id == cl.id)
            .order_by(ClaimReview.created_at.asc())
        ).all()

        claims_out.append(
            {
                "id": str(cl.id),
                "type": cl.type.value,
                "text": cl.text,
                "evidence_state": cl.evidence_state.value,
                "limitation_note": cl.limitation_note,
                "is_stale": cl.is_stale,
                "stale_reason": cl.stale_reason,
                "source_diff": cl.source_diff,
                "evidence": evidence_out,
                "reviews": [
                    {
                        "id": str(rv.id),
                        "action": rv.action.value,
                        "old_text": rv.old_text,
                        "new_text": rv.new_text,
                        "note": rv.note,
                        "created_at": rv.created_at.isoformat(),
                    }
                    for rv in reviews
                ],
            }
        )

    receipts = db.scalars(
        select(Receipt)
        .where(Receipt.handover_version_id == handover.id)
        .order_by(Receipt.acknowledged_at.desc())
    ).all()

    return {
        "id": str(handover.id),
        "project_id": str(handover.project_id),
        "version": handover.version,
        "status": handover.status.value,
        "approved_by": str(handover.approved_by) if handover.approved_by else None,
        "approved_at": handover.approved_at.isoformat() if handover.approved_at else None,
        "summary_notes": handover.summary_notes,
        "viewer_role": current_user.role.value,
        "claims": claims_out,
        "receipts": [
            {
                "id": str(r.id),
                "successor_id": str(r.successor_id),
                "acknowledged_at": r.acknowledged_at.isoformat(),
                "notes": r.notes,
            }
            for r in receipts
        ],
    }


@router.get("/approved")
def get_approved_handover(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    handover = db.scalar(
        select(HandoverVersion)
        .where(
            HandoverVersion.project_id == project_id,
            HandoverVersion.status == HandoverStatus.approved,
        )
        .order_by(HandoverVersion.version.desc())
    )
    if not handover:
        raise HTTPException(status_code=404, detail="No approved handover version available yet.")
    return _serialize_handover(db, handover, current_user)


@router.get("/latest")
def get_latest_handover(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    handover = db.scalar(
        select(HandoverVersion)
        .where(HandoverVersion.project_id == project_id)
        .order_by(HandoverVersion.version.desc())
    )
    if not handover:
        raise HTTPException(status_code=404, detail="No handover versions found for project.")
    return _serialize_handover(db, handover, current_user)


@router.get("/{handover_id}")
def get_handover(
    handover_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    handover = db.get(HandoverVersion, handover_id)
    if not handover:
        raise HTTPException(status_code=404, detail="Handover version not found")
    return _serialize_handover(db, handover, current_user)


@router.get("/{handover_id}/export")
def export_handover_markdown(
    handover_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    handover = db.get(HandoverVersion, handover_id)
    if not handover:
        raise HTTPException(status_code=404, detail="Handover version not found")

    data = _serialize_handover(db, handover, current_user)
    lines = [
        f"# Relay Handover v{data['version']} ({data['status'].upper()})",
        f"Viewer role: `{current_user.role.value}`",
        "",
    ]
    for c in data["claims"]:
        lines.append(f"- **[{c['type'].upper()} | {c['evidence_state']}]** {c['text']}")
        if c["limitation_note"]:
            lines.append(f"  - *Limitation:* {c['limitation_note']}")
        for ev in c["evidence"]:
            if ev.get("restricted"):
                lines.append("  - Citation: Evidence not available to you.")
                continue
            sha = f" @ `{ev['version_sha'][:7]}`" if ev.get("version_sha") else ""
            lines.append(f"  - Citation: `{ev['source_title']}`{sha} — \"{ev['quote_span']}\"")
    return {"format": "markdown", "content": "\n".join(lines)}


@router.post("/generate")
def generate_handover(
    payload: GenerateHandoverRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    target_id = payload.successor_id or project.successor_user_id
    target_user = db.get(User, target_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Target successor user not found")

    permitted_chunks = retrieve_permitted_chunks(db, project.id, target_user)
    extraction, _prompt = extract_claims_from_chunks(permitted_chunks, use_mock=payload.use_mock)
    valid_claims, rejected_claims = validate_extracted_claims(extraction.claims, permitted_chunks)

    max_ver = db.scalar(
        select(func.coalesce(func.max(HandoverVersion.version), 0)).where(
            HandoverVersion.project_id == project.id
        )
    )
    handover = HandoverVersion(
        project_id=project.id,
        version=(max_ver or 0) + 1,
        status=HandoverStatus.draft,
        summary_notes=f"Generated for successor {target_user.name} from {len(permitted_chunks)} permitted chunks.",
    )
    db.add(handover)
    db.flush()

    claim_roles = list({target_user.role.value, "reviewer", "outgoing"})
    saved_claims_out = []

    for vc in valid_claims:
        claim = Claim(
            project_id=project.id,
            handover_version_id=handover.id,
            text=vc.text,
            type=ClaimType(vc.type),
            evidence_state=vc.evidence_state,
            limitation_note=vc.limitation_note,
            allowed_roles=claim_roles,
            allowed_user_ids=[target_user.id],
        )
        db.add(claim)
        db.flush()

        for ev in vc.evidence:
            db.add(
                ClaimEvidence(
                    claim_id=claim.id,
                    chunk_id=uuid.UUID(ev.chunk_id),
                    quote_span=ev.quote_span,
                    quote_start_offset=ev.quote_start_offset,
                    quote_end_offset=ev.quote_end_offset,
                    stance=ev.stance,
                )
            )

        saved_claims_out.append(
            {
                "id": str(claim.id),
                "type": claim.type.value,
                "text": claim.text,
                "evidence_state": claim.evidence_state.value,
                "limitation_note": claim.limitation_note,
                "evidence_count": len(vc.evidence),
            }
        )

    db.flush()
    conflict_summary = detect_conflicts_and_gaps(
        db=db,
        project_id=project.id,
        handover_version_id=handover.id,
        use_llm=not (payload.use_mock if payload.use_mock is not None else True),
    )

    db.add(
        AuditLog(
            project_id=project.id,
            actor_id=current_user.id,
            action="handover_generated",
            entity_type="handover_version",
            entity_id=handover.id,
            details={
                "target_successor_id": str(target_user.id),
                "permitted_chunk_count": len(permitted_chunks),
                "claims_saved": len(saved_claims_out),
                "claims_rejected": len(rejected_claims),
                "conflicts_created": conflict_summary["conflicts_created"],
            },
        )
    )
    db.commit()

    return {
        "handover_version_id": str(handover.id),
        "version": handover.version,
        "status": handover.status.value,
        "target_successor_id": str(target_user.id),
        "permitted_chunk_count": len(permitted_chunks),
        "claims_saved": saved_claims_out,
        "rejected_claims": [
            {"text": r.text, "reason": r.reason} for r in rejected_claims
        ],
        "conflict_summary": conflict_summary,
    }


@router.post("/{handover_id}/approve")
def approve_handover(
    handover_id: uuid.UUID,
    payload: ApproveHandoverRequest = ApproveHandoverRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.reviewer:
        raise HTTPException(status_code=403, detail="Only a reviewer can approve a handover.")

    handover = db.get(HandoverVersion, handover_id)
    if not handover:
        raise HTTPException(status_code=404, detail="Handover version not found")

    if handover.status == HandoverStatus.approved:
        raise HTTPException(status_code=409, detail="Handover version is already approved.")

    open_conflicts = db.scalars(
        select(Conflict).where(
            Conflict.project_id == handover.project_id,
            Conflict.status == ConflictStatus.open,
        )
    ).all()
    if open_conflicts:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve handover while {len(open_conflicts)} open conflict(s) remain unresolved.",
        )

    critical_types = {ClaimType.state, ClaimType.decision, ClaimType.risk, ClaimType.ownership}
    unreviewed_critical = db.scalars(
        select(Claim).where(
            Claim.project_id == handover.project_id,
            (Claim.handover_version_id == handover.id) | (Claim.handover_version_id.is_(None)),
            Claim.type.in_(critical_types),
            Claim.evidence_state.in_(["supported", "conflicting"]),
        )
    ).all()
    if unreviewed_critical:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve handover while {len(unreviewed_critical)} critical claim(s) remain unreviewed (confirm, edit, reject, or flag missing first).",
        )

    stale_claims = db.scalars(
        select(Claim).where(
            Claim.project_id == handover.project_id,
            (Claim.handover_version_id == handover.id) | (Claim.handover_version_id.is_(None)),
            Claim.is_stale.is_(True),
        )
    ).all()
    if stale_claims:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve handover while {len(stale_claims)} stale claim(s) await re-review after a source update.",
        )

    # Mark any prior approved versions as superseded
    prior_approved = db.scalars(
        select(HandoverVersion).where(
            HandoverVersion.project_id == handover.project_id,
            HandoverVersion.status == HandoverStatus.approved,
            HandoverVersion.id != handover.id,
        )
    ).all()
    for prior in prior_approved:
        prior.status = HandoverStatus.superseded

    now = datetime.now(timezone.utc)
    handover.status = HandoverStatus.approved
    handover.approved_by = current_user.id
    handover.approved_at = now
    if payload.summary_notes:
        handover.summary_notes = payload.summary_notes

    db.add(
        AuditLog(
            project_id=handover.project_id,
            actor_id=current_user.id,
            action="handover_approved",
            entity_type="handover_version",
            entity_id=handover.id,
            details={"version": handover.version},
        )
    )
    db.commit()

    return {
        "id": str(handover.id),
        "version": handover.version,
        "status": handover.status.value,
        "approved_by": str(handover.approved_by),
        "approved_at": handover.approved_at.isoformat(),
    }


@router.post("/{handover_id}/acknowledge")
def acknowledge_handover(
    handover_id: uuid.UUID,
    payload: AcknowledgeHandoverRequest = AcknowledgeHandoverRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.successor:
        raise HTTPException(status_code=403, detail="Only the successor can acknowledge receipt.")

    handover = db.get(HandoverVersion, handover_id)
    if not handover:
        raise HTTPException(status_code=404, detail="Handover version not found")

    if handover.status != HandoverStatus.approved:
        raise HTTPException(
            status_code=409,
            detail="Handover must be approved by a reviewer before acknowledgement.",
        )

    receipt = Receipt(
        project_id=handover.project_id,
        handover_version_id=handover.id,
        successor_id=current_user.id,
        acknowledged_at=datetime.now(timezone.utc),
        notes=payload.notes,
    )
    db.add(receipt)
    db.add(
        AuditLog(
            project_id=handover.project_id,
            actor_id=current_user.id,
            action="receipt_acknowledged",
            entity_type="receipt",
            entity_id=receipt.id,
            details={"handover_version_id": str(handover.id), "version": handover.version},
        )
    )
    db.commit()

    return {
        "id": str(receipt.id),
        "handover_version_id": str(receipt.handover_version_id),
        "successor_id": str(receipt.successor_id),
        "acknowledged_at": receipt.acknowledged_at.isoformat(),
        "notes": receipt.notes,
    }

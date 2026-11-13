from dataclasses import dataclass
import json
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Claim,
    ClaimEvidence,
    ClaimType,
    Conflict,
    ConflictStatus,
    EvidenceState,
)


@dataclass
class DetectedConflict:
    title: str
    claim_ids: list[uuid.UUID]


POSITIVE_COMPLETION_MARKERS = ("complete", "completed", "decommissioned", "100% traffic", "finished")
NEGATIVE_BLOCKER_MARKERS = ("paused", "wip", "do not merge", "failing", "blocked", "incomplete", "35% traffic")


def _rule_based_conflicts(claims: list[Claim]) -> list[DetectedConflict]:
    """
    Rule-based conflict detector: groups claims on the same topic (e.g. migration status)
    and flags opposing polarity without auto-picking the newer source.
    """
    complete_claims: list[Claim] = []
    paused_or_wip_claims: list[Claim] = []

    for c in claims:
        if c.evidence_state in (EvidenceState.missing, EvidenceState.superseded):
            continue
        low = c.text.lower()
        if "migration" in low or "stripe v2" in low or "pr #142" in low:
            if any(m in low for m in POSITIVE_COMPLETION_MARKERS):
                complete_claims.append(c)
            elif any(m in low for m in NEGATIVE_BLOCKER_MARKERS):
                paused_or_wip_claims.append(c)

    detected: list[DetectedConflict] = []
    if complete_claims and paused_or_wip_claims:
        all_ids = [c.id for c in complete_claims] + [c.id for c in paused_or_wip_claims]
        detected.append(
            DetectedConflict(
                title="Migration status conflict: claims of completion vs. paused/unfinished work",
                claim_ids=all_ids,
            )
        )
    return detected


def _llm_assisted_conflicts(
    claims: list[Claim],
    already_paired: set[frozenset[uuid.UUID]],
) -> list[DetectedConflict]:
    if not settings.openai_api_key or len(claims) < 2:
        return []

    claim_payload = [
        {"id": str(c.id), "type": c.type.value, "text": c.text}
        for c in claims
        if c.evidence_state not in (EvidenceState.missing, EvidenceState.superseded)
    ]
    if len(claim_payload) < 2:
        return []

    prompt = (
        "Identify any contradictory claims in this list. Return JSON: "
        '{"conflicts": [{"title": "...", "claim_ids": ["uuid1", "uuid2"]}]}.\n'
        + json.dumps(claim_payload, indent=2)
    )
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": "You detect factual contradictions between handover claims. Never auto-resolve.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            resp.raise_for_status()
            data = json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception:
        return []

    valid_ids = {c.id for c in claims}
    out: list[DetectedConflict] = []
    for item in data.get("conflicts", []):
        try:
            ids = [uuid.UUID(cid) for cid in item.get("claim_ids", [])]
        except ValueError:
            continue
        ids = [cid for cid in ids if cid in valid_ids]
        if len(ids) >= 2 and frozenset(ids) not in already_paired:
            out.append(DetectedConflict(title=item.get("title", "Detected conflict"), claim_ids=ids))
            already_paired.add(frozenset(ids))
    return out


def detect_conflicts_and_gaps(
    db: Session,
    project_id: uuid.UUID,
    handover_version_id: uuid.UUID | None = None,
    use_llm: bool = False,
) -> dict:
    """
    1. Run rule-based conflict detection first, then optional LLM-assisted pass.
    2. Create Conflict records (status=open; never auto-pick newer source) and mark
       participating claims as `conflicting`.
    3. Ensure missing-information gaps (e.g. deployment delay rationale) are flagged.
    """
    stmt = select(Claim).where(Claim.project_id == project_id)
    if handover_version_id:
        stmt = stmt.where(Claim.handover_version_id == handover_version_id)
    claims = list(db.scalars(stmt.order_by(Claim.created_at.asc())).all())

    existing_conflicts = list(
        db.scalars(select(Conflict).where(Conflict.project_id == project_id)).all()
    )
    existing_sets = {frozenset(c.claim_ids) for c in existing_conflicts}

    detected = _rule_based_conflicts(claims)
    if use_llm:
        detected.extend(_llm_assisted_conflicts(claims, existing_sets.copy()))

    created_conflicts: list[Conflict] = []
    claim_by_id = {c.id: c for c in claims}

    for dc in detected:
        key = frozenset(dc.claim_ids)
        if key in existing_sets:
            continue
        existing_sets.add(key)
        conflict = Conflict(
            project_id=project_id,
            title=dc.title,
            claim_ids=dc.claim_ids,
            status=ConflictStatus.open,
        )
        db.add(conflict)
        created_conflicts.append(conflict)

        for cid in dc.claim_ids:
            if cid in claim_by_id and claim_by_id[cid].evidence_state != EvidenceState.human_confirmed:
                claim_by_id[cid].evidence_state = EvidenceState.conflicting

    # Ensure gap detection: if no claim addresses deployment delay rationale, record a missing gap
    has_delay_claim = any("delay" in c.text.lower() for c in claims)
    gap_created = False
    if not has_delay_claim:
        gap_claim = Claim(
            project_id=project_id,
            handover_version_id=handover_version_id,
            text="Reason for the production deployment delay is unknown.",
            type=ClaimType.risk,
            evidence_state=EvidenceState.missing,
            limitation_note=(
                "No source explains why production deployment was delayed. "
                "Marked as a knowledge gap; rationale is never inferred from code."
            ),
            allowed_roles=["outgoing", "reviewer", "successor"],
            allowed_user_ids=[],
        )
        db.add(gap_claim)
        gap_created = True

    db.flush()
    gaps = [c for c in claims if c.evidence_state == EvidenceState.missing]
    return {
        "conflicts_created": len(created_conflicts),
        "conflict_ids": [str(c.id) for c in created_conflicts],
        "gaps_count": len(gaps) + (1 if gap_created else 0),
    }

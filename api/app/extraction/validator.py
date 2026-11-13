from dataclasses import dataclass

from app.extraction.llm_client import ExtractedClaimItem, PermittedChunk
from app.models import EvidenceStance, EvidenceState


@dataclass
class ValidatedEvidence:
    chunk_id: str
    quote_span: str
    quote_start_offset: int
    quote_end_offset: int
    stance: EvidenceStance


@dataclass
class ValidatedClaim:
    type: str
    text: str
    evidence_state: EvidenceState
    limitation_note: str | None
    evidence: list[ValidatedEvidence]


@dataclass
class RejectedClaim:
    text: str
    reason: str


def validate_extracted_claims(
    raw_claims: list[ExtractedClaimItem],
    permitted_chunks: list[PermittedChunk],
) -> tuple[list[ValidatedClaim], list[RejectedClaim]]:
    """
    Verify every cited quote exists verbatim inside its permitted chunk.
    Reject any claim whose quotes fail verbatim verification or that lacks evidence
    without being explicitly marked `missing`.
    """
    chunk_map = {c.chunk_id: c for c in permitted_chunks}
    valid_claims: list[ValidatedClaim] = []
    rejected_claims: list[RejectedClaim] = []

    for item in raw_claims:
        if item.evidence_state == "missing" and not item.evidence:
            valid_claims.append(
                ValidatedClaim(
                    type=item.type,
                    text=item.text,
                    evidence_state=EvidenceState.missing,
                    limitation_note=item.limitation_note
                    or "No supporting evidence found in permitted sources.",
                    evidence=[],
                )
            )
            continue

        verified_evidence: list[ValidatedEvidence] = []
        rejection_reasons: list[str] = []

        for ref in item.evidence:
            chunk = chunk_map.get(ref.chunk_id)
            if not chunk:
                rejection_reasons.append(f"Chunk {ref.chunk_id} is not in permitted chunks.")
                continue

            if not ref.quote_span:
                rejection_reasons.append(f"Empty quote_span for chunk {ref.chunk_id}.")
                continue

            idx = chunk.text.find(ref.quote_span)
            if idx == -1:
                rejection_reasons.append(
                    f"Quote not found verbatim in chunk {ref.chunk_id}: {ref.quote_span[:60]!r}"
                )
                continue

            abs_start = chunk.start_offset + idx
            abs_end = abs_start + len(ref.quote_span)
            verified_evidence.append(
                ValidatedEvidence(
                    chunk_id=ref.chunk_id,
                    quote_span=ref.quote_span,
                    quote_start_offset=abs_start,
                    quote_end_offset=abs_end,
                    stance=EvidenceStance(ref.stance),
                )
            )

        if not verified_evidence:
            reason = "; ".join(rejection_reasons) or "No valid verbatim evidence provided."
            rejected_claims.append(RejectedClaim(text=item.text, reason=reason))
            continue

        valid_claims.append(
            ValidatedClaim(
                type=item.type,
                text=item.text,
                evidence_state=EvidenceState(item.evidence_state),
                limitation_note=item.limitation_note,
                evidence=verified_evidence,
            )
        )

    return valid_claims, rejected_claims

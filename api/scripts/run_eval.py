"""Evaluation harness reporting real observed counts on the labelled dataset."""

import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from app.extraction.conflict_detector import _rule_based_conflicts
from app.extraction.llm_client import ExtractedClaimItem, ExtractedEvidenceRef, PermittedChunk
from app.extraction.validator import validate_extracted_claims
from app.models import Claim, ClaimType, EvidenceState, UserRole
from app.permissions import can_access_record


def run_evaluation() -> dict:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "eval_dataset.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    chunks = [PermittedChunk(**c) for c in data["chunks"]]

    # 1. Factual claims: citation support vs unsupported rejection
    raw_factual = [
        ExtractedClaimItem(
            type="state",
            text=item["text"],
            evidence_state="supported",
            evidence=[ExtractedEvidenceRef(chunk_id=item["chunk_id"], quote_span=item["quote_span"])],
        )
        for item in data["factual_claims"]
    ]
    valid_factual, rejected_factual = validate_extracted_claims(raw_factual, chunks)

    # 2. Conflicts
    conflicts_detected = 0
    for pair in data["conflict_cases"]:
        pid = uuid.uuid4()
        c_a = Claim(
            id=uuid.uuid4(),
            project_id=pid,
            text=pair["claim_a"],
            type=ClaimType.state,
            evidence_state=EvidenceState.supported,
            allowed_roles=["reviewer"],
            allowed_user_ids=[],
        )
        c_b = Claim(
            id=uuid.uuid4(),
            project_id=pid,
            text=pair["claim_b"],
            type=ClaimType.state,
            evidence_state=EvidenceState.supported,
            allowed_roles=["reviewer"],
            allowed_user_ids=[],
        )
        if _rule_based_conflicts([c_a, c_b]):
            conflicts_detected += 1

    # 3. Missing-information cases
    raw_missing = [
        ExtractedClaimItem(
            type="risk",
            text=m["text"],
            evidence_state="missing",
            limitation_note=m["limitation_note"],
            evidence=[],
        )
        for m in data["missing_cases"]
    ]
    valid_missing, _ = validate_extracted_claims(raw_missing, chunks)

    # 4. Access-control cases
    access_passed = 0
    access_failures = 0
    for ac in data["access_cases"]:
        user = SimpleNamespace(id=uuid.UUID(ac["user_id"]), role=UserRole(ac["role"]))
        allowed_uids = [uuid.UUID(u) for u in ac["allowed_user_ids"]]
        actual = can_access_record(user, ac["allowed_roles"], allowed_uids)
        if actual == ac["expected"]:
            access_passed += 1
        else:
            access_failures += 1

    report = {
        "factual_claims_total": len(data["factual_claims"]),
        "citation_supported_count": len(valid_factual),
        "unsupported_rejected_count": len(rejected_factual),
        "conflicts_total": len(data["conflict_cases"]),
        "conflicts_detected_count": conflicts_detected,
        "missing_cases_total": len(data["missing_cases"]),
        "missing_flagged_count": len(valid_missing),
        "access_cases_total": len(data["access_cases"]),
        "access_passed_count": access_passed,
        "access_failures_count": access_failures,
    }
    return report


if __name__ == "__main__":
    print(json.dumps(run_evaluation(), indent=2))

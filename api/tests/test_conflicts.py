import uuid

from fastapi.testclient import TestClient
import pytest

from app.extraction.conflict_detector import _rule_based_conflicts
from app.main import app
from app.models import Claim, ClaimType, EvidenceState


def test_rule_based_conflict_detector_flags_complete_vs_paused():
    c1 = Claim(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        text="README says Payments Migration is COMPLETE and legacy v1 endpoints are decommissioned.",
        type=ClaimType.state,
        evidence_state=EvidenceState.supported,
        allowed_roles=["reviewer"],
        allowed_user_ids=[],
    )
    c2 = Claim(
        id=uuid.uuid4(),
        project_id=c1.project_id,
        text="Oct 28 note says Payments migration is PAUSED at 35% traffic.",
        type=ClaimType.state,
        evidence_state=EvidenceState.supported,
        allowed_roles=["reviewer"],
        allowed_user_ids=[],
    )
    c3 = Claim(
        id=uuid.uuid4(),
        project_id=c1.project_id,
        text="PR #142 is WIP and failing webhook replay tests; DO NOT MERGE.",
        type=ClaimType.unfinished,
        evidence_state=EvidenceState.supported,
        allowed_roles=["reviewer"],
        allowed_user_ids=[],
    )

    detected = _rule_based_conflicts([c1, c2, c3])
    assert len(detected) == 1
    assert set(detected[0].claim_ids) == {c1.id, c2.id, c3.id}


@pytest.mark.integration
def test_planted_conflicts_gaps_and_reviewer_resolution():
    """
    Requires PostgreSQL running + migrated + seeded.
    """
    client = TestClient(app)
    project_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    reviewer_id = "22222222-2222-2222-2222-222222222222"
    successor_id = "33333333-3333-3333-3333-333333333333"

    # 1. Planted conflict shows both sides with date, source, and exact passage
    cf_resp = client.get(f"/conflicts?project_id={project_id}", headers={"X-User-Id": reviewer_id})
    assert cf_resp.status_code == 200
    conflicts = cf_resp.json()["conflicts"]
    assert len(conflicts) >= 1
    open_cf = next(c for c in conflicts if c["status"] == "open")
    assert len(open_cf["sides"]) >= 2
    for side in open_cf["sides"]:
        assert len(side["passages"]) >= 1
        assert side["passages"][0]["source_title"]
        assert side["passages"][0]["source_date"]
        assert side["passages"][0]["quote_span"]

    # 2. Planted gaps include missing deployment delay rationale and unassigned TASK-88
    gaps_resp = client.get(f"/conflicts/gaps?project_id={project_id}", headers={"X-User-Id": successor_id})
    assert gaps_resp.status_code == 200
    gaps_data = gaps_resp.json()
    assert any("delay" in g["text"].lower() for g in gaps_data["missing_claims"])
    assert any("TASK-88" in r["item"] for r in gaps_data["unassigned_responsibilities"])

    # 3. Non-reviewer cannot resolve conflict
    paused_side = next(s for s in open_cf["sides"] if "paused" in s["text"].lower())
    readme_side = next(s for s in open_cf["sides"] if "complete" in s["text"].lower())

    forbidden = client.post(
        f"/conflicts/{open_cf['id']}/resolve",
        headers={"X-User-Id": successor_id},
        json={"winning_claim_id": paused_side["claim_id"], "resolution_note": "Pick paused"},
    )
    assert forbidden.status_code == 403

    # 4. Reviewer must provide non-empty explanation
    bad_req = client.post(
        f"/conflicts/{open_cf['id']}/resolve",
        headers={"X-User-Id": reviewer_id},
        json={"winning_claim_id": paused_side["claim_id"], "resolution_note": ""},
    )
    assert bad_req.status_code == 422

    # 5. Reviewer resolves conflict -> winning claim human_confirmed, README claim superseded
    resolved = client.post(
        f"/conflicts/{open_cf['id']}/resolve",
        headers={"X-User-Id": reviewer_id},
        json={
            "winning_claim_id": paused_side["claim_id"],
            "resolution_note": "README was written Oct 1 before the Oct 28 incident; traffic is still at 35%.",
        },
    )
    assert resolved.status_code == 200
    res_data = resolved.json()
    assert res_data["status"] == "resolved"
    assert res_data["winning_claim_id"] == paused_side["claim_id"]
    assert readme_side["claim_id"] in res_data["superseded_claim_ids"]

from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import UserRole
from app.permissions import can_access_record, redact_evidence_if_denied

PROJECT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OUTGOING_ID = "11111111-1111-1111-1111-111111111111"
REVIEWER_ID = "22222222-2222-2222-2222-222222222222"
SUCCESSOR_ID = "33333333-3333-3333-3333-333333333333"


def _fake_user(uid: str, role: UserRole):
    return SimpleNamespace(id=uuid.UUID(uid), role=role)


def test_01_central_can_access_record_role_and_user_allowlist():
    succ = _fake_user(SUCCESSOR_ID, UserRole.successor)
    rev = _fake_user(REVIEWER_ID, UserRole.reviewer)

    assert can_access_record(rev, ["reviewer"], []) is True
    assert can_access_record(succ, ["reviewer"], []) is False
    assert can_access_record(succ, [], [uuid.UUID(SUCCESSOR_ID)]) is True
    assert can_access_record(succ, [], []) is False


def test_02_redact_evidence_if_denied_neutral_placeholder():
    succ = _fake_user(SUCCESSOR_ID, UserRole.successor)
    src = SimpleNamespace(allowed_roles=["reviewer"], allowed_user_ids=[uuid.UUID(REVIEWER_ID)])
    chunk = SimpleNamespace(allowed_roles=["reviewer"], allowed_user_ids=[uuid.UUID(REVIEWER_ID)])
    payload = {
        "source_title": "notes/2026-11-05-manager-1on1.md",
        "quote_span": "CONFIDENTIAL: Stripe rate-card renegotiation",
        "source_uri": "upload://notes/2026-11-05-manager-1on1.md",
    }

    redacted = redact_evidence_if_denied(succ, src, chunk, payload)
    assert redacted == {"restricted": True, "message": "Evidence not available to you"}
    assert "CONFIDENTIAL" not in str(redacted)
    assert "manager-1on1" not in str(redacted)


@pytest.mark.integration
def test_03_successor_list_sources_excludes_manager_only_note():
    client = TestClient(app)
    resp = client.get(f"/sources?project_id={PROJECT_ID}", headers={"X-User-Id": SUCCESSOR_ID})
    assert resp.status_code == 200
    titles = {s["title"] for s in resp.json()["sources"]}
    assert "notes/2026-11-05-manager-1on1.md" not in titles


@pytest.mark.integration
def test_04_direct_url_guessing_restricted_source_returns_403():
    client = TestClient(app)
    rev_sources = client.get(f"/sources?project_id={PROJECT_ID}", headers={"X-User-Id": REVIEWER_ID}).json()["sources"]
    restricted_id = next(s["id"] for s in rev_sources if s["title"] == "notes/2026-11-05-manager-1on1.md")

    denied = client.get(f"/sources/{restricted_id}", headers={"X-User-Id": SUCCESSOR_ID})
    assert denied.status_code == 403
    assert "rate-card" not in denied.text


@pytest.mark.integration
def test_05_direct_url_guessing_restricted_chunk_preview_returns_403():
    client = TestClient(app)
    rev_sources = client.get(
        f"/sources?project_id={PROJECT_ID}&include_chunks=true",
        headers={"X-User-Id": REVIEWER_ID},
    ).json()["sources"]
    restricted_src = next(s for s in rev_sources if s["title"] == "notes/2026-11-05-manager-1on1.md")
    chunk_id = restricted_src["chunks"][0]["id"]

    denied = client.get(f"/sources/chunks/{chunk_id}", headers={"X-User-Id": SUCCESSOR_ID})
    assert denied.status_code == 403
    assert "CONFIDENTIAL" not in denied.text


@pytest.mark.integration
def test_06_search_endpoint_excludes_restricted_note():
    client = TestClient(app)
    rev_search = client.get(
        f"/sources/search?project_id={PROJECT_ID}&q=renegotiation",
        headers={"X-User-Id": REVIEWER_ID},
    )
    assert rev_search.status_code == 200
    assert rev_search.json()["count"] >= 1

    succ_search = client.get(
        f"/sources/search?project_id={PROJECT_ID}&q=renegotiation",
        headers={"X-User-Id": SUCCESSOR_ID},
    )
    assert succ_search.status_code == 200
    assert succ_search.json()["count"] == 0


@pytest.mark.integration
def test_07_generation_for_successor_never_includes_restricted_note():
    client = TestClient(app)
    gen = client.post(
        "/handovers/generate",
        headers={"X-User-Id": REVIEWER_ID},
        json={"project_id": PROJECT_ID, "successor_id": SUCCESSOR_ID, "use_mock": True},
    )
    assert gen.status_code == 200
    for c in gen.json()["claims_saved"]:
        assert "rate-card" not in c["text"].lower()
        assert "confidential" not in c["text"].lower()


@pytest.mark.integration
def test_08_handover_endpoint_hides_restricted_claims_and_citations():
    client = TestClient(app)
    hv = client.get(f"/handovers/latest?project_id={PROJECT_ID}", headers={"X-User-Id": SUCCESSOR_ID})
    assert hv.status_code == 200
    body_text = hv.text.lower()
    assert "rate-card" not in body_text
    assert "2026-11-05-manager-1on1" not in body_text


@pytest.mark.integration
def test_09_export_endpoint_never_leaks_restricted_note():
    client = TestClient(app)
    hv = client.get(f"/handovers/latest?project_id={PROJECT_ID}", headers={"X-User-Id": REVIEWER_ID}).json()
    exp = client.get(f"/handovers/{hv['id']}/export", headers={"X-User-Id": SUCCESSOR_ID})
    assert exp.status_code == 200
    content = exp.json()["content"].lower()
    assert "rate-card" not in content
    assert "2026-11-05-manager-1on1" not in content


@pytest.mark.integration
def test_10_acknowledge_receipt_requires_approved_handover_and_successor_role():
    client = TestClient(app)
    hv = client.get(f"/handovers/latest?project_id={PROJECT_ID}", headers={"X-User-Id": REVIEWER_ID}).json()

    # Non-successor cannot acknowledge
    wrong_role = client.post(
        f"/handovers/{hv['id']}/acknowledge",
        headers={"X-User-Id": REVIEWER_ID},
        json={"notes": "test"},
    )
    assert wrong_role.status_code == 403

    # Unapproved draft cannot be acknowledged
    if hv["status"] != "approved":
        not_approved = client.post(
            f"/handovers/{hv['id']}/acknowledge",
            headers={"X-User-Id": SUCCESSOR_ID},
            json={"notes": "test"},
        )
        assert not_approved.status_code == 409

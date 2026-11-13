import json
from pathlib import Path
import uuid

from fastapi.testclient import TestClient
import pytest

from app.ingestion.chunker import chunk_text
from app.ingestion.normalizer import normalize_uploaded_content
from app.main import app


def test_chunker_preserves_exact_span_offsets():
    text = (
        "# Heading\n\n"
        "First paragraph with details about rollback.\n\n"
        "Second paragraph explaining the idempotency key mismatch."
    )
    chunks = chunk_text(text, max_chars=60)
    assert len(chunks) >= 2
    for ch in chunks:
        assert text[ch.start_offset : ch.end_offset] == ch.text
        assert ch.line_start >= 1
        assert ch.line_end >= ch.line_start


def test_normalizer_handles_md_csv_and_json():
    src_type, md = normalize_uploaded_content("notes.md", b"# Sync\r\nPaused at 35%.")
    assert src_type == "meeting_note"
    assert "Paused at 35%." in md

    csv_bytes = b"id,title,owner\nTASK-1,Verify DLQ,\nTASK-2,Rotate key,Maya\n"
    src_type, csv_norm = normalize_uploaded_content("tasks.csv", csv_bytes)
    assert src_type == "task_export"
    assert "(unassigned/empty)" in csv_norm
    assert "Maya" in csv_norm

    json_bytes = json.dumps([{"id": "T-1", "title": "Check retry", "owner": ""}]).encode()
    src_type, json_norm = normalize_uploaded_content("tasks.json", json_bytes)
    assert src_type == "task_export"
    assert "Check retry" in json_norm
    assert "(unassigned/empty)" in json_norm


@pytest.mark.integration
def test_sources_endpoints_with_seed_data():
    """
    Requires PostgreSQL running + migrated + seeded (`alembic upgrade head && python -m app.seed`).
    """
    client = TestClient(app)
    project_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    reviewer_id = "22222222-2222-2222-2222-222222222222"
    successor_id = "33333333-3333-3333-3333-333333333333"

    # 1. Permission-filtered GET /sources on seed data
    rev_resp = client.get(f"/sources?project_id={project_id}", headers={"X-User-Id": reviewer_id})
    assert rev_resp.status_code == 200
    rev_titles = {s["title"] for s in rev_resp.json()["sources"]}
    assert "notes/2026-11-05-manager-1on1.md" in rev_titles

    succ_resp = client.get(f"/sources?project_id={project_id}", headers={"X-User-Id": successor_id})
    assert succ_resp.status_code == 200
    succ_titles = {s["title"] for s in succ_resp.json()["sources"]}
    assert "notes/2026-11-05-manager-1on1.md" not in succ_titles

    # Successor cannot fetch restricted source directly
    restricted_id = next(
        s["id"] for s in rev_resp.json()["sources"] if s["title"] == "notes/2026-11-05-manager-1on1.md"
    )
    denied = client.get(f"/sources/{restricted_id}", headers={"X-User-Id": successor_id})
    assert denied.status_code == 403

    # 2. Upload without explicit access policy must be rejected (422)
    no_policy = client.post(
        "/sources/upload",
        headers={"X-User-Id": reviewer_id},
        data={"project_id": project_id, "allowed_roles": "[]", "allowed_user_ids": "[]"},
        files={"file": ("note.md", b"Test note", "text/markdown")},
    )
    assert no_policy.status_code == 422

    # 3. Upload with explicit access policy succeeds
    ok_upload = client.post(
        "/sources/upload",
        headers={"X-User-Id": reviewer_id},
        data={
            "project_id": project_id,
            "title": "Post-mortem addendum",
            "allowed_roles": '["reviewer", "successor"]',
        },
        files={"file": ("addendum.md", b"## Addendum\nRetry queue drained.", "text/markdown")},
    )
    assert ok_upload.status_code == 200
    assert ok_upload.json()["chunk_count"] >= 1

    # 4. GitHub fixture ingestion succeeds offline
    gh_resp = client.post(
        "/sources/github",
        headers={"X-User-Id": reviewer_id},
        json={
            "project_id": project_id,
            "repo": "acme-student-team/payments-service",
            "use_fixture": True,
        },
    )
    assert gh_resp.status_code == 200
    assert gh_resp.json()["sources_created"] >= 3

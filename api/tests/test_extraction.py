from fastapi.testclient import TestClient
import pytest

from app.extraction.llm_client import (
    ExtractedClaimItem,
    ExtractedEvidenceRef,
    PermittedChunk,
    build_extraction_prompt,
    extract_claims_from_chunks,
)
from app.extraction.validator import validate_extracted_claims
from app.main import app


def _sample_chunks() -> list[PermittedChunk]:
    return [
        PermittedChunk(
            chunk_id="11111111-1111-1111-1111-111111111111",
            source_id="22222222-2222-2222-2222-222222222222",
            source_title="notes/2026-10-28-sync.md",
            source_type="meeting_note",
            source_date="2026-10-28T12:00:00+00:00",
            version_sha=None,
            text="Rollback procedure: set PAYMENTS_V2_ENABLED=false in infra/flags.yaml.",
            start_offset=100,
            end_offset=169,
        )
    ]


def test_citation_validity_verbatim_and_offsets():
    chunks = _sample_chunks()
    raw = [
        ExtractedClaimItem(
            type="decision",
            text="Disable Stripe v2 via feature flag to roll back.",
            evidence_state="supported",
            evidence=[
                ExtractedEvidenceRef(
                    chunk_id=chunks[0].chunk_id,
                    quote_span="set PAYMENTS_V2_ENABLED=false in infra/flags.yaml.",
                )
            ],
        )
    ]
    valid, rejected = validate_extracted_claims(raw, chunks)
    assert len(valid) == 1
    assert len(rejected) == 0
    ev = valid[0].evidence[0]
    rel_start = ev.quote_start_offset - chunks[0].start_offset
    rel_end = ev.quote_end_offset - chunks[0].start_offset
    assert chunks[0].text[rel_start:rel_end] == ev.quote_span


def test_unsupported_claim_rejection_and_missing_preservation():
    chunks = _sample_chunks()
    raw = [
        # Fabricated quote not present verbatim in chunk
        ExtractedClaimItem(
            type="decision",
            text="Rollback uses Kubernetes helm rollback.",
            evidence_state="supported",
            evidence=[
                ExtractedEvidenceRef(
                    chunk_id=chunks[0].chunk_id,
                    quote_span="run helm rollback checkout-api",
                )
            ],
        ),
        # Non-permitted / non-existent chunk ID
        ExtractedClaimItem(
            type="risk",
            text="Manager-only secret claim",
            evidence_state="supported",
            evidence=[
                ExtractedEvidenceRef(
                    chunk_id="99999999-9999-9999-9999-999999999999",
                    quote_span="CONFIDENTIAL",
                )
            ],
        ),
        # Explicit missing claim without evidence should be kept
        ExtractedClaimItem(
            type="risk",
            text="Deployment delay rationale is unknown.",
            evidence_state="missing",
            limitation_note="No source explains the delay.",
            evidence=[],
        ),
    ]
    valid, rejected = validate_extracted_claims(raw, chunks)
    assert len(rejected) == 2
    assert len(valid) == 1
    assert valid[0].evidence_state.value == "missing"
    assert valid[0].limitation_note == "No source explains the delay."


def test_prompt_excludes_unpermitted_chunks():
    chunks = _sample_chunks()
    prompt = build_extraction_prompt(chunks)
    assert "PAYMENTS_V2_ENABLED=false" in prompt
    assert "rate-card renegotiation" not in prompt
    resp, used_prompt = extract_claims_from_chunks(chunks, use_mock=True)
    assert "rate-card renegotiation" not in used_prompt
    assert all("rate-card" not in c.text for c in resp.claims)


@pytest.mark.integration
def test_generate_handover_endpoint_respects_permissions(monkeypatch):
    """
    Requires PostgreSQL running + migrated + seeded.
    Verifies restricted manager-only note never enters the LLM prompt or output
    when generating for successor Alex Rivera.
    """
    captured_prompts: list[str] = []
    from app.extraction import llm_client

    orig_extract = llm_client.extract_claims_from_chunks

    def spy_extract(chunks, use_mock=None):
        resp, prompt = orig_extract(chunks, use_mock=True)
        captured_prompts.append(prompt)
        return resp, prompt

    monkeypatch.setattr("app.routers.handovers.extract_claims_from_chunks", spy_extract)

    client = TestClient(app)
    project_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    reviewer_id = "22222222-2222-2222-2222-222222222222"
    successor_id = "33333333-3333-3333-3333-333333333333"

    resp = client.post(
        "/handovers/generate",
        headers={"X-User-Id": reviewer_id},
        json={"project_id": project_id, "successor_id": successor_id, "use_mock": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_successor_id"] == successor_id
    assert len(data["claims_saved"]) >= 4

    # Restricted manager note must NEVER appear in the LLM prompt or generated claims
    assert len(captured_prompts) == 1
    assert "rate-card renegotiation" not in captured_prompts[0]
    assert "2026-11-05-manager-1on1" not in captured_prompts[0]
    for c in data["claims_saved"]:
        assert "rate-card" not in c["text"].lower()

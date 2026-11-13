from dataclasses import dataclass
import json
import re
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from app.config import settings


@dataclass(frozen=True)
class PermittedChunk:
    chunk_id: str
    source_id: str
    source_title: str
    source_type: str
    source_date: str | None
    version_sha: str | None
    text: str
    start_offset: int
    end_offset: int


class ExtractedEvidenceRef(BaseModel):
    chunk_id: str
    quote_span: str
    stance: Literal["supports", "contradicts", "context"] = "supports"


class ExtractedClaimItem(BaseModel):
    type: Literal[
        "decision",
        "unfinished",
        "dependency",
        "ownership",
        "risk",
        "next_action",
        "state",
    ]
    text: str
    evidence_state: Literal["supported", "conflicting", "missing"] = "supported"
    limitation_note: str | None = None
    evidence: list[ExtractedEvidenceRef] = Field(default_factory=list)


class ExtractionResponse(BaseModel):
    claims: list[ExtractedClaimItem] = Field(default_factory=list)


SYSTEM_PROMPT = """You are Relay, a source-backed project handover extraction engine.
Given ONLY the permitted source chunks below, extract structured handover claims.

STRICT RULES:
1. Every non-missing claim MUST cite one or more chunk_ids with an EXACT, VERBATIM quote_span copied character-for-character from that chunk's text.
2. NEVER invent, paraphrase, or alter quote_span text.
3. NEVER infer intent or rationale (such as why a deployment was delayed) from code alone. If important context is missing, emit a claim with evidence_state="missing", evidence=[], and an explicit limitation_note.
4. If two sources contradict each other (e.g. README says complete, later note says paused), emit both with evidence_state="conflicting".
5. Return ONLY valid JSON matching: {"claims": [{"type": "...", "text": "...", "evidence_state": "supported|conflicting|missing", "limitation_note": null|"...", "evidence": [{"chunk_id": "...", "quote_span": "...", "stance": "supports|contradicts|context"}]}]}."""


def build_extraction_prompt(chunks: list[PermittedChunk]) -> str:
    serialized = [
        {
            "chunk_id": c.chunk_id,
            "source_title": c.source_title,
            "source_type": c.source_type,
            "source_date": c.source_date,
            "version_sha": c.version_sha,
            "text": c.text,
        }
        for c in chunks
    ]
    return (
        "Extract handover claims (current state, decisions, unfinished work, dependencies, "
        "ownership gaps, risks, and immediate next actions) from these permitted chunks:\n\n"
        + json.dumps(serialized, indent=2)
    )


def _mock_extract(chunks: list[PermittedChunk]) -> ExtractionResponse:
    """Deterministic offline extraction engine operating strictly on `chunks`."""
    claims: list[ExtractedClaimItem] = []

    has_complete = any("COMPLETE" in c.text for c in chunks)
    has_paused = any("PAUSED" in c.text for c in chunks)

    for c in chunks:
        txt = c.text
        if "COMPLETE" in txt:
            match = re.search(r"Payments Migration Status: COMPLETE\.[^\n]*", txt)
            quote = match.group(0) if match else txt[:140]
            claims.append(
                ExtractedClaimItem(
                    type="state",
                    text="README claims the Payments Migration is COMPLETE and legacy v1 endpoints are decommissioned.",
                    evidence_state="conflicting" if has_paused else "supported",
                    evidence=[ExtractedEvidenceRef(chunk_id=c.chunk_id, quote_span=quote)],
                )
            )

        if "PAUSED" in txt:
            match = re.search(r"[^\n]*PAUSED[^\n]*", txt)
            quote = match.group(0).strip() if match else txt[:140]
            claims.append(
                ExtractedClaimItem(
                    type="state",
                    text="Payments migration is currently PAUSED at 35% traffic due to an idempotency key mismatch on retry.",
                    evidence_state="conflicting" if has_complete else "supported",
                    evidence=[ExtractedEvidenceRef(chunk_id=c.chunk_id, quote_span=quote)],
                )
            )

        if "Rollback procedure" in txt or "PAYMENTS_V2_ENABLED=false" in txt:
            match = re.search(r"Rollback procedure:[^\n]*", txt)
            quote = match.group(0).strip() if match else txt[:160]
            claims.append(
                ExtractedClaimItem(
                    type="decision",
                    text="Rollback procedure: set PAYMENTS_V2_ENABLED=false in infra/flags.yaml, redeploy checkout-api, and drain the retry queue.",
                    evidence_state="supported",
                    evidence=[ExtractedEvidenceRef(chunk_id=c.chunk_id, quote_span=quote)],
                )
            )

        if "DO NOT MERGE" in txt or "failing webhook replay" in txt:
            match = re.search(r"[^\n]*DO NOT MERGE[^\n]*", txt)
            quote = match.group(0).strip() if match else txt[:160]
            claims.append(
                ExtractedClaimItem(
                    type="unfinished",
                    text="PR #142 is unfinished and failing webhook replay integration tests; do not merge until DLQ replay is verified.",
                    evidence_state="supported",
                    evidence=[ExtractedEvidenceRef(chunk_id=c.chunk_id, quote_span=quote)],
                )
            )

        if "TASK-88" in txt and ("No assignee" in txt or "(unassigned/empty)" in txt or ",," in txt):
            match = re.search(r"[^\n]*TASK-88[^\n]*", txt)
            quote = match.group(0).strip() if match else txt[:160]
            claims.append(
                ExtractedClaimItem(
                    type="ownership",
                    text="TASK-88 (Verify webhook dead-letter queue replay) is blocked and has no assigned owner.",
                    evidence_state="supported",
                    evidence=[ExtractedEvidenceRef(chunk_id=c.chunk_id, quote_span=quote)],
                )
            )

    # Explicit missing-evidence check: never invent deployment delay rationale
    combined_lower = " ".join(c.text.lower() for c in chunks)
    if "delay" not in combined_lower and "oct 15" not in combined_lower:
        claims.append(
            ExtractedClaimItem(
                type="risk",
                text="Reason for the production deployment delay is unknown.",
                evidence_state="missing",
                limitation_note=(
                    "No permitted source explains the deployment delay rationale. "
                    "Intent is not inferred from code alone."
                ),
                evidence=[],
            )
        )

    return ExtractionResponse(claims=claims)


def extract_claims_from_chunks(
    chunks: list[PermittedChunk],
    use_mock: bool | None = None,
) -> tuple[ExtractionResponse, str]:
    """
    Call the LLM (or offline mock) with ONLY the permitted chunks.
    Returns (ExtractionResponse, prompt_used).
    """
    prompt = build_extraction_prompt(chunks)
    should_mock = use_mock if use_mock is not None else (not bool(settings.openai_api_key))

    if should_mock:
        return _mock_extract(chunks), prompt

    with httpx.Client(timeout=45.0) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.llm_model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        resp.raise_for_status()
        raw_content = resp.json()["choices"][0]["message"]["content"]
        parsed = ExtractionResponse.model_validate_json(raw_content)
        return parsed, prompt

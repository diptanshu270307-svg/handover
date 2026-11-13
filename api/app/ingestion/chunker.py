from dataclasses import dataclass
from pathlib import Path
import re
import uuid

from app.config import settings


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    text: str
    start_offset: int
    end_offset: int
    line_start: int
    line_end: int


def save_to_storage(project_id: uuid.UUID, filename: str, content: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    base = Path(settings.object_storage_dir)
    target = base / str(project_id) / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target)


def _line_number_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def chunk_text(full_text: str, max_chars: int = 800) -> list[TextChunk]:
    """
    Split text into deterministic chunks on paragraph/line boundaries while preserving
    exact character offsets and 1-based line numbers into `full_text`.
    """
    if not full_text or not full_text.strip():
        return []

    # Split into non-empty paragraph/line blocks keeping exact offsets
    blocks: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", full_text):
        segment = match.group(0).strip()
        if not segment:
            continue
        start = full_text.find(segment, match.start(), match.end())
        end = start + len(segment)
        blocks.append((start, end, segment))

    if not blocks:
        stripped = full_text.strip()
        start = full_text.find(stripped)
        end = start + len(stripped)
        return [
            TextChunk(
                chunk_index=0,
                text=stripped,
                start_offset=start,
                end_offset=end,
                line_start=_line_number_at(full_text, start),
                line_end=_line_number_at(full_text, max(start, end - 1)),
            )
        ]

    chunks: list[TextChunk] = []
    cur_start: int | None = None
    cur_end: int = 0

    for start, end, _ in blocks:
        if cur_start is None:
            cur_start = start
            cur_end = end
            continue

        if (end - cur_start) <= max_chars:
            cur_end = end
        else:
            slice_text = full_text[cur_start:cur_end]
            chunks.append(
                TextChunk(
                    chunk_index=len(chunks),
                    text=slice_text,
                    start_offset=cur_start,
                    end_offset=cur_end,
                    line_start=_line_number_at(full_text, cur_start),
                    line_end=_line_number_at(full_text, max(cur_start, cur_end - 1)),
                )
            )
            cur_start = start
            cur_end = end

    if cur_start is not None:
        slice_text = full_text[cur_start:cur_end]
        chunks.append(
            TextChunk(
                chunk_index=len(chunks),
                text=slice_text,
                start_offset=cur_start,
                end_offset=cur_end,
                line_start=_line_number_at(full_text, cur_start),
                line_end=_line_number_at(full_text, max(cur_start, cur_end - 1)),
            )
        )

    return chunks

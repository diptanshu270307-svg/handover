import csv
import io
import json


def normalize_uploaded_content(filename: str, raw_bytes: bytes) -> tuple[str, str]:
    """
    Normalize uploaded Markdown/text or CSV/JSON task export into UTF-8 text.
    Returns (inferred_source_type, normalized_text).
    """
    lower = filename.lower()
    text = raw_bytes.decode("utf-8", errors="replace")

    if lower.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return "task_export", text.strip()
        lines: list[str] = []
        for idx, row in enumerate(reader, start=1):
            parts = [f"{k}: {(v or '').strip() or '(unassigned/empty)'}" for k, v in row.items() if k]
            lines.append(f"Task Row {idx} | " + " | ".join(parts))
        return "task_export", "\n\n".join(lines) if lines else text.strip()

    if lower.endswith(".json"):
        data = json.loads(text)
        items = data if isinstance(data, list) else data.get("tasks", [data])
        lines = []
        for idx, item in enumerate(items, start=1):
            if isinstance(item, dict):
                parts = [f"{k}: {v if v not in (None, '') else '(unassigned/empty)'}" for k, v in item.items()]
                lines.append(f"Task Item {idx} | " + " | ".join(parts))
            else:
                lines.append(f"Task Item {idx} | {item}")
        return "task_export", "\n\n".join(lines) if lines else text.strip()

    # Default: Markdown or plain text meeting/project note
    return "meeting_note", text.replace("\r\n", "\n").strip()

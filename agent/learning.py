"""
Learn from every call: record outcomes and inject recent learnings into the system prompt.
Each call's metrics are written to data/feedback.jsonl; new calls get a short "LEARN FROM RECENT CALLS" block.
"""
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

# Default paths (can be overridden by config)
FEEDBACK_PATH = Path("data/feedback.jsonl")


def _learning_snippet_from_metrics(metrics: "CallMetrics") -> str:
    """Turn this call's outcome into a one-line learning (what went wrong or right)."""
    d = metrics.finalize()
    conv = d.get("conversation", {})
    quality = d.get("quality", {})

    escalated = conv.get("escalated", False)
    escalation_reason = (conv.get("escalation_reason") or "").strip().lower()
    tool_errors = quality.get("tool_errors", 0)
    tools_called = quality.get("tools_called") or []
    task_completed = conv.get("task_completed")
    task_type = conv.get("task_type", "")
    interruptions = conv.get("interruptions_count", 0)

    parts = []
    if escalated:
        if "name" in escalation_reason or "spelling" in escalation_reason or "correct" in escalation_reason:
            parts.append("escalation_after_name_correction")
        else:
            parts.append(f"escalation:{escalation_reason[:80]}")
    if tool_errors > 0:
        parts.append(f"tool_errors:{','.join(tools_called[-3:])}")
    if task_type == "booking" and task_completed is False and not escalated:
        parts.append("booking_incomplete")
    if interruptions >= 4:
        parts.append("many_interruptions")

    if not parts:
        return "ok"
    return "; ".join(parts[:3])  # cap 3 signals


def record_feedback(metrics: "CallMetrics", feedback_path: Path | None = None) -> None:
    """
    Append one call's feedback to data/feedback.jsonl so future calls can learn.
    Call this after log_and_persist_metrics (on_client_disconnected).
    """
    path = feedback_path or FEEDBACK_PATH
    try:
        d = metrics.finalize()
        learning = _learning_snippet_from_metrics(metrics)
        record = {
            "ts": datetime.now().isoformat(),
            "session_id": d.get("session_id", ""),
            "outcome": "escalated" if d.get("conversation", {}).get("escalated") else ("ok" if d.get("conversation", {}).get("task_completed") is not False else "incomplete"),
            "learning": learning,
            "tool_errors": d.get("quality", {}).get("tool_errors", 0),
            "escalation_reason": d.get("conversation", {}).get("escalation_reason") or "",
            "tools_called": d.get("quality", {}).get("tools_called", []),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.warning("Failed to record feedback: {}", e)


def get_recent_learnings(
    max_entries: int = 50,
    max_chars: int = 600,
    feedback_path: Path | None = None,
) -> str:
    """
    Read last N feedback entries and return a short "LEARN FROM RECENT CALLS" block.
    Only includes entries that represent mistakes (not "ok" or empty learning).
    """
    path = feedback_path or FEEDBACK_PATH
    if not path.exists():
        return ""

    lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        logger.warning("Failed to read feedback file: {}", e)
        return ""

    # Last N entries (newest last)
    entries: list[dict] = []
    for line in reversed(lines[-max_entries:]):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Collect mistake patterns (avoid repeating the same line)
    seen: set[str] = set()
    bullets: list[str] = []
    for e in entries:
        learning = (e.get("learning") or "").strip()
        if not learning or learning == "ok":
            continue
        if learning in seen:
            continue
        seen.add(learning)

        if "escalation_after_name_correction" in learning:
            bullets.append("Do NOT escalate when the caller is only correcting their name spelling; update the name and continue.")
        elif learning.startswith("escalation:"):
            reason = learning.replace("escalation:", "").strip()[:60]
            bullets.append(f"Recent escalation reason: {reason}. Only escalate for medical advice, billing, or when they ask for a person.")
        elif learning.startswith("tool_errors:"):
            tools = learning.replace("tool_errors:", "").strip()
            bullets.append(f"Tool errors recently on: {tools}. Confirm tool results before continuing.")
        elif "booking_incomplete" in learning:
            bullets.append("Bookings sometimes did not complete; confirm all details and call book_appointment only after caller confirms.")
        elif "many_interruptions" in learning:
            bullets.append("Keep responses short to avoid frequent interruptions.")

        if len(bullets) >= 5:
            break

    if not bullets:
        return ""

    block = "LEARN FROM RECENT CALLS:\n" + "\n".join(f"- {b}" for b in bullets)
    if len(block) > max_chars:
        block = block[: max_chars - 3] + "..."
    return block

"""
Per-call metrics for voice agent quality measurement.
Accumulates data during a call; writes structured JSON at call end.
"""
import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger


class CallMetrics:
    """
    Accumulates metrics for a single call. Updated by observers and tool handlers.
    Call finalize() at call end to compute totals and write output.
    """

    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.timestamp = datetime.now().isoformat()
        self.start_time = datetime.now()

        # Per-turn latency (we get total_response_ms from latency observer)
        self.turns: list[dict] = []

        # Conversation
        self.total_turns = 0
        self.escalated = False
        self.escalation_reason: str | None = None

        # Quality
        self.tools_called: list[str] = []
        self.tool_errors = 0
        self.model_used: str | None = None
        self.caller_recognized: bool | None = None
        self.confirmation_accepted_first_try: bool | None = None

        # Barge-ins
        self.interruptions_count = 0

    def record_turn(self, total_response_ms: float, breakdown: dict | None = None):
        """Record one user→bot turn."""
        turn = {"total_response_ms": round(total_response_ms, 2)}
        if breakdown:
            turn.update(breakdown)
        self.turns.append(turn)
        self.total_turns = len(self.turns)

    def record_tool_call(self, name: str):
        """Record a tool invocation."""
        self.tools_called.append(name)

    def record_tool_error(self):
        """Record a failed tool call."""
        self.tool_errors += 1

    def record_barge_in(self):
        """Record user interruption."""
        self.interruptions_count += 1

    def record_escalation(self, reason: str):
        """Record escalation to human."""
        self.escalated = True
        self.escalation_reason = reason

    def set_caller_recognized(self, recognized: bool):
        """Set whether caller was known (returning)."""
        self.caller_recognized = recognized

    def set_model_used(self, model: str):
        """Set which LLM model was used."""
        self.model_used = model

    def set_task_info(self, task_type: str | None = None, completed: bool | None = None):
        """Set task type and completion (inferred from tools)."""
        if hasattr(self, "_task_type"):
            return  # already set
        self._task_type = task_type
        self._task_completed = completed

    def to_dict(self) -> dict:
        """Build final metrics dict for JSON output."""
        end_time = datetime.now()
        total_call_duration_s = (end_time - self.start_time).total_seconds()

        # Infer task_type from tools
        task_type = "faq"
        if "book_appointment" in self.tools_called:
            task_type = "booking"
        elif "reschedule_appointment" in self.tools_called:
            task_type = "rescheduling"
        elif "cancel_appointment" in self.tools_called:
            task_type = "cancellation"
        elif self.escalated:
            task_type = "escalation"

        task_completed = None
        if task_type == "booking" and "book_appointment" in self.tools_called:
            task_completed = self.tool_errors == 0  # heuristic
        elif task_type == "escalation":
            task_completed = False

        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "end_timestamp": end_time.isoformat(),
            "latency": {
                "turns": self.turns,
                "avg_response_ms": round(
                    sum(t.get("total_response_ms", 0) for t in self.turns) / len(self.turns)
                    if self.turns else 0,
                    2,
                ),
            },
            "conversation": {
                "total_turns": self.total_turns,
                "total_call_duration_s": round(total_call_duration_s, 2),
                "task_type": task_type,
                "task_completed": task_completed,
                "escalated": self.escalated,
                "escalation_reason": self.escalation_reason,
                "interruptions_count": self.interruptions_count,
            },
            "quality": {
                "tools_called": self.tools_called,
                "tool_errors": self.tool_errors,
                "model_used": self.model_used,
                "caller_recognized": self.caller_recognized,
                "confirmation_accepted_first_try": self.confirmation_accepted_first_try,
            },
        }

    def finalize(self) -> dict:
        """Compute final dict and return it."""
        return self.to_dict()


def parse_breakdown_events(breakdown) -> dict:
    """Extract ms values from latency breakdown if possible."""
    out: dict[str, float] = {}
    try:
        for ev in breakdown.chronological_events():
            s = str(ev).lower()
            if "user" in s and "turn" in s and "ms" in s:
                # Try to parse number
                for part in s.split():
                    if part.replace(".", "").isdigit():
                        out["user_turn_duration_ms"] = float(part)
                        break
            if "stt" in s or "deepgram" in s:
                for part in s.split():
                    if part.replace(".", "").isdigit():
                        out["stt_time_ms"] = float(part)
                        break
            if "llm" in s or "ttfb" in s:
                for part in s.split():
                    if part.replace(".", "").isdigit():
                        out["llm_ttfb_ms"] = float(part)
                        break
            if "tts" in s or "cartesia" in s:
                for part in s.split():
                    if part.replace(".", "").isdigit():
                        out["tts_ttfb_ms"] = float(part)
                        break
    except Exception:
        pass
    return out


def _sync_write_jsonl(path: Path, line: str) -> None:
    """Synchronous file append for executor (avoids blocking event loop)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


async def _write_metrics_async(metrics_dict: dict, path: str) -> None:
    """Write metrics to jsonl file without blocking. Ensures zero latency impact."""
    try:
        p = Path(path)
        line = json.dumps(metrics_dict) + "\n"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_write_jsonl, p, line)
    except Exception as e:
        logger.warning("Failed to write metrics to %s: %s", path, e)


def log_and_persist_metrics(metrics: "CallMetrics", jsonl_path: str = "data/metrics.jsonl") -> None:
    """Log metrics as [CALL_METRICS] and schedule async write to file."""
    d = metrics.finalize()
    logger.info("[CALL_METRICS] %s", json.dumps(d))
    asyncio.create_task(_write_metrics_async(d, jsonl_path))

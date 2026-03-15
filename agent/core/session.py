"""
Call session — tracks everything that happens during one phone call.
Created when a caller connects, destroyed when they disconnect.
All logs and DB writes can be tagged with session_id for debugging.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class CallOutcome(str, Enum):
    COMPLETED = "completed"   # Caller got what they needed
    ESCALATED = "escalated"   # Transferred to human
    ABANDONED = "abandoned"   # Caller hung up mid-conversation
    ERROR = "error"          # Something went wrong


class ToolInvocation(BaseModel):
    tool_name: str
    arguments: dict
    result: str
    duration_ms: float
    success: bool
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CallSession(BaseModel):
    """
    One instance per call. Can be passed to tool handlers and services.
    """
    session_id: str = Field(default_factory=lambda: f"call-{uuid.uuid4().hex[:12]}")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    caller_phone: str | None = None
    caller_name: str | None = None
    transport_type: str = "webrtc"
    outcome: CallOutcome | None = None

    tool_invocations: list[ToolInvocation] = Field(default_factory=list)
    turn_count: int = 0
    total_latency_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)

    def record_tool_call(
        self,
        tool_name: str,
        args: dict,
        result: str,
        duration_ms: float,
        success: bool,
    ) -> None:
        self.tool_invocations.append(
            ToolInvocation(
                tool_name=tool_name,
                arguments=args,
                result=result[:200],
                duration_ms=duration_ms,
                success=success,
            )
        )

    def record_error(self, error: str) -> None:
        self.errors.append(f"{datetime.now(timezone.utc).isoformat()}: {error}")

    def end(self, outcome: CallOutcome) -> None:
        self.ended_at = datetime.now(timezone.utc)
        self.outcome = outcome

    @property
    def duration_seconds(self) -> float | None:
        if self.ended_at and self.started_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None

    def summary(self) -> dict:
        """For logging at end of call."""
        return {
            "session_id": self.session_id,
            "duration_s": self.duration_seconds,
            "turns": self.turn_count,
            "tools_called": len(self.tool_invocations),
            "errors": len(self.errors),
            "outcome": self.outcome.value if self.outcome else "unknown",
        }

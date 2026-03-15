"""
Context window management for long calls.
Keeps the system prompt + recent messages, summarizes older ones.

Strategy:
  - System prompt: always kept (position 0)
  - Recent messages: last N exchanges kept verbatim
  - Older messages: summarized into a single "conversation so far" message

Prevents context overflow while maintaining conversation coherence.
"""
from loguru import logger

from agent.config import settings


class ContextManager:
    """
    Wraps LLMContext to manage message history.

    Usage:
        cm = ContextManager(context)
        cm.maybe_trim()  # Call after each turn
    """

    def __init__(self, context) -> None:
        self.context = context
        self.max_messages = settings.max_context_messages
        self.trim_threshold = settings.context_summary_threshold

    def message_count(self) -> int:
        return len(self.context.messages)

    def maybe_trim(self) -> bool:
        """
        If context exceeds threshold, summarize older messages and keep recent ones.
        Returns True if trimming occurred.
        """
        if self.message_count() < self.trim_threshold:
            return False

        logger.info(
            "Context trimming: {count} messages exceeds threshold {threshold}",
            count=self.message_count(),
            threshold=self.trim_threshold,
        )

        messages = self.context.messages
        system_prompt = messages[0]

        keep_count = 20
        recent = messages[-keep_count:]
        old = messages[1:-keep_count]

        summary = self._summarize(old)

        self.context.messages.clear()
        self.context.messages.append(system_prompt)
        self.context.messages.append({
            "role": "system",
            "content": f"Summary of earlier conversation: {summary}",
        })
        self.context.messages.extend(recent)

        logger.info(
            "Context trimmed: {old_count} → {new_count} messages",
            old_count=len(messages),
            new_count=self.message_count(),
        )
        return True

    def _summarize(self, messages: list[dict]) -> str:
        """
        Extractive summary of old messages (no LLM call).
        """
        summary_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if not content or not isinstance(content, str):
                continue

            if role == "assistant":
                if any(
                    kw in content.lower()
                    for kw in ["booked", "confirmed", "cancelled", "rescheduled", "appointment id", "apt-"]
                ):
                    summary_parts.append(f"Aria confirmed: {content[:150]}")

            if role == "user" and len(content) > 10:
                summary_parts.append(f"Caller said: {content[:100]}")

            if role == "tool" or (role == "assistant" and "function" in str(msg)):
                summary_parts.append(f"Tool result: {content[:150]}")

        if not summary_parts:
            return "Earlier conversation covered general questions and greetings."

        return " | ".join(summary_parts[:10])

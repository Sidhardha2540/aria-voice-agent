"""
Filter that strips function-call markup from LLM text before TTS.
Prevents the bot from literally speaking "< function = check_availability >{...}</ function >".
"""
import re
from typing import Optional

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# Match from "< function" to "</ function >" so we strip the whole block (including JSON)
_FUNCTION_BLOCK_RE = re.compile(
    r"<\s*function\s*(?:=\s*[^>]+)?>\s*.*?</\s*function\s*>",
    re.IGNORECASE | re.DOTALL,
)


class FunctionCallFilter(FrameProcessor):
    """
    Buffers LLMTextFrame content and strips any `< function = ... >{...}</ function >`
    blocks before forwarding to TTS. Only forwards non-empty text.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buffer = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMTextFrame):
            self._buffer += frame.text
            # Try to push safe content: text before a function block, or after a closed block
            to_push = self._flush_safe()
            if to_push:
                await self.push_frame(LLMTextFrame(text=to_push), direction)
        elif isinstance(frame, LLMFullResponseEndFrame):
            # Strip any function blocks in remaining buffer and push the rest
            while True:
                to_push = self._flush_safe()
                if to_push:
                    await self.push_frame(LLMTextFrame(text=to_push), direction)
                else:
                    break
            cleaned = _FUNCTION_BLOCK_RE.sub("", self._buffer).strip()
            if cleaned:
                await self.push_frame(LLMTextFrame(text=cleaned), direction)
            self._buffer = ""
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

    def _flush_safe(self) -> Optional[str]:
        """
        If the buffer contains a complete function block, remove it and return
        any text that is safe to send to TTS (before the block). Then keep
        in buffer only what's after the block.
        """
        match = _FUNCTION_BLOCK_RE.search(self._buffer)
        if not match:
            return None
        # Safe content is everything before the match
        safe = self._buffer[: match.start()].strip()
        # Keep in buffer only what's after the match (might be more text or another block)
        self._buffer = self._buffer[match.end() :]
        return safe if safe else None

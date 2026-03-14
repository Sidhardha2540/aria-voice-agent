"""
Context trimming — limits conversation history to prevent slowdown over long calls.
"""
from pipecat.frames.frames import Frame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.processors.aggregators.llm_context import LLMContext

from agent.config import MAX_CONTEXT_TURNS


class ContextTrimmer(FrameProcessor):
    """Trims LLM context to last N turns when over limit."""

    def __init__(self, context: LLMContext, max_turns: int = MAX_CONTEXT_TURNS, **kwargs):
        super().__init__(**kwargs)
        self._context = context
        self._max_messages = max_turns * 2

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        messages = self._context.messages
        non_system = len(messages) - 1
        if non_system > self._max_messages:
            trimmed = non_system - self._max_messages
            self._context.messages[:] = [messages[0]] + messages[1 + trimmed:]
        await self.push_frame(frame, direction)

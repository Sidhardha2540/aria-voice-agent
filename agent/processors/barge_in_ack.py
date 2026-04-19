"""
After a barge-in, prepend a short acknowledgement to the next LLM text so the reply
sounds human (review: force acknowledgements on interruption).
"""
import random

from loguru import logger
from pipecat.frames.frames import Frame, LLMTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_ACKS = ("Sure,", "Got it,", "Of course,", "No problem,")


class BargeInAckProcessor(FrameProcessor):
    """Prepends one acknowledgement phrase to the first LLM text after barge-in."""

    def __init__(self, metrics_ref: dict) -> None:
        super().__init__()
        self._metrics_ref = metrics_ref

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMTextFrame) and frame.text:
            if self._metrics_ref.get("barge_in_ack_pending"):
                prefix = random.choice(_ACKS)
                new_text = f"{prefix} {frame.text.lstrip()}"
                logger.debug("[BARGE-IN] prepended ack: {}", prefix)
                frame = LLMTextFrame(text=new_text)
                self._metrics_ref["barge_in_ack_pending"] = False
        await self.push_frame(frame, direction)

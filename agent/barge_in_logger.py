"""
Barge-in / interruption logging.
Logs when the user interrupts Aria's speech so we can measure and debug.
"""
import asyncio
from datetime import datetime
from typing import Callable

from loguru import logger
from pipecat.frames.frames import Frame, StartInterruptionFrame, UserStartedSpeakingFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


class BargeInLogger(FrameProcessor):
    """Logs [BARGE-IN] when user interrupts bot speech (StartInterruptionFrame / UserStartedSpeakingFrame)."""

    def __init__(
        self,
        on_barge_in: Callable[[], None] | None = None,
        metrics_ref: dict | None = None,
    ):
        super().__init__()
        self._on_barge_in = on_barge_in
        self._metrics_ref = metrics_ref

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (StartInterruptionFrame, UserStartedSpeakingFrame)):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            logger.info(f"[BARGE-IN] User interrupted bot at {ts}")
            if self._metrics_ref is not None:
                self._metrics_ref["barge_in_ack_pending"] = True
            if self._on_barge_in:
                try:
                    if asyncio.iscoroutinefunction(self._on_barge_in):
                        await self._on_barge_in()
                    else:
                        self._on_barge_in()
                except Exception:
                    pass
        await self.push_frame(frame, direction)

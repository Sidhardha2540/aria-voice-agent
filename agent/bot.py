"""
Main Pipecat pipeline for Aria — the AI healthcare receptionist.
Transport is created by the factory (webrtc/twilio/daily); pipeline is built in core.pipeline.
"""
from agent.config import (
    ENABLE_BACKCHANNELING,
    ENABLE_DUAL_LLM,
    GROQ_MODEL,
)
from agent.core.pipeline import create_pipeline
from agent.prompts import GREETING_PROMPT
from agent.transport.factory import create_transport
from agent.metrics import CallMetrics, log_and_persist_metrics, parse_breakdown_events
from loguru import logger
from pipecat.frames.frames import ClientConnectedFrame, TTSSpeakFrame
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments


async def _prewarm_db():
    from agent.database.db import get_shared_db
    await get_shared_db()


async def run_bot(transport):
    """Core bot logic — transport-agnostic. Cleans up DB on exit."""
    await _prewarm_db()
    if ENABLE_BACKCHANNELING:
        logger.warning("[BACKCHANNEL] ENABLE_BACKCHANNELING=true but not implemented; see agent/backchanneling.py TODO")
    metrics_ref = {}
    breakdown_ref = {}
    pipeline, context = create_pipeline(transport, metrics_ref)

    latency_observer = UserBotLatencyObserver()

    @latency_observer.event_handler("on_first_bot_speech_latency")
    async def _on_first_speech(observer, latency_seconds):
        logger.info(f"[LATENCY] First bot speech (greeting): {latency_seconds:.2f}s")

    @latency_observer.event_handler("on_latency_measured")
    async def _on_latency(observer, latency_seconds):
        logger.info(f"[LATENCY] User→Bot: {latency_seconds:.2f}s")
        if latency_seconds > 0.3:
            logger.warning("[LATENCY] Above 300ms target!")
        m = metrics_ref.get("metrics")
        if m:
            b = breakdown_ref.pop("last", None)
            breakdown = parse_breakdown_events(b) if b else None
            m.record_turn(latency_seconds * 1000, breakdown)

    @latency_observer.event_handler("on_latency_breakdown")
    async def _on_breakdown(observer, breakdown):
        logger.info("[LATENCY] Breakdown:")
        for event in breakdown.chronological_events():
            logger.info(f"  {event}")
        breakdown_ref["last"] = breakdown

    task = PipelineTask(
        pipeline,
        observers=[latency_observer],
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, webrtc_connection):
        metrics_ref["metrics"] = CallMetrics()
        if not ENABLE_DUAL_LLM:
            metrics_ref["metrics"].set_model_used(GROQ_MODEL)
        # Push frames through pipeline: latency marker + greeting via TTS (bypasses LLM for consistent intro)
        await task.queue_frames([
            ClientConnectedFrame(),
            TTSSpeakFrame(GREETING_PROMPT, append_to_context=True),
        ])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, webrtc_connection):
        m = metrics_ref.pop("metrics", None)
        if m:
            log_and_persist_metrics(m)
        await task.cancel()

    # handle_sigint=True so Ctrl+C cancels the pipeline and the process can exit cleanly
    runner = PipelineRunner(handle_sigint=True)
    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Entry point for the Pipecat development runner."""
    if not isinstance(runner_args, SmallWebRTCRunnerArguments):
        raise ValueError("This bot only supports SmallWebRTC. Run with: python -m agent.bot -t webrtc")

    from agent.config import settings
    if not settings.deepgram_api_key or not settings.groq_api_key or not settings.cartesia_api_key:
        raise ValueError("Missing API keys. Set DEEPGRAM_API_KEY, GROQ_API_KEY, CARTESIA_API_KEY in .env")

    transport, _ = await create_transport(runner_args)
    await run_bot(transport)


def _register_exit_cleanup():
    """Close DB on process exit so Ctrl+C stops the process completely."""
    import atexit
    import asyncio

    def _shutdown_db():
        try:
            from agent.database.manager import db_manager
            if db_manager._conn is None and db_manager._pool is None:
                return
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(asyncio.wait_for(db_manager.shutdown(), timeout=2.0))
                logger.info("Database closed on exit.")
            except asyncio.TimeoutError:
                logger.warning("Database shutdown timed out; exiting anyway.")
            finally:
                loop.close()
        except Exception as e:
            logger.debug("Exit cleanup: {}", e)

    atexit.register(_shutdown_db)


if __name__ == "__main__":
    _register_exit_cleanup()
    from agent.config import settings
    logger.info(
        "[CONFIG] Latency: utterance_end_ms=%s endpointing=%s model=%s tts_low_latency=%s",
        settings.deepgram_utterance_end_ms,
        settings.deepgram_endpointing,
        settings.groq_model,
        settings.tts_low_latency,
    )
    from pipecat.runner.run import main
    main()

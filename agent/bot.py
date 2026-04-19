"""
Main Pipecat pipeline for Aria — the AI healthcare receptionist.
Transport is created by the factory (webrtc/twilio/daily); pipeline is built in core.pipeline.
"""
from agent.config import (
    ENABLE_BACKCHANNELING,
    ENABLE_DUAL_LLM,
    OPENAI_MODEL,
)
from agent.core.pipeline import create_pipeline
from agent.prompts import GREETING_PROMPT
from agent.transport.factory import create_transport
from agent.metrics import CallMetrics, log_and_persist_metrics, parse_breakdown_events
from agent.learning import record_feedback
from agent.latency_tracker import LatencyTracker
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
    metrics_ref: dict = {}
    breakdown_ref: dict = {}
    pipeline, context = create_pipeline(transport, metrics_ref)

    latency_observer = UserBotLatencyObserver()

    @latency_observer.event_handler("on_first_bot_speech_latency")
    async def _on_first_speech(observer, latency_seconds):
        logger.info(f"[LATENCY] First bot speech (greeting): {latency_seconds:.2f}s")

    @latency_observer.event_handler("on_latency_measured")
    async def _on_latency(observer, latency_seconds):
        # Store total; we'll compute and record "after STT" in _on_breakdown
        breakdown_ref["last_latency_secs"] = latency_seconds

    @latency_observer.event_handler("on_latency_breakdown")
    async def _on_breakdown(observer, breakdown):
        logger.info("[LATENCY] Breakdown:")
        for event in breakdown.chronological_events():
            logger.info(f"  {event}")
        # Latency we report = only after STT (speaker stopped → transcript ready is excluded)
        total_secs = breakdown_ref.pop("last_latency_secs", None)
        user_turn_secs = getattr(breakdown, "user_turn_secs", None)
        if total_secs is not None and user_turn_secs is not None:
            after_stt_secs = max(0.0, total_secs - user_turn_secs)
        else:
            after_stt_secs = total_secs if total_secs is not None else 0.0
        after_stt_ms = after_stt_secs * 1000
        # Natural human gap between one person stopping and the other starting is ~200-300ms. Aim for that.
        logger.info(f"[LATENCY] After STT: {after_stt_ms:.0f}ms (natural gap target: 200-300ms)")
        if after_stt_ms <= 300:
            logger.info("[LATENCY] Within natural gap — great.")
        elif after_stt_ms <= 500:
            logger.info("[LATENCY] Acceptable (under 500ms).")
        else:
            logger.warning(
                "[LATENCY] Above 500ms: {:.0f}ms — aim for 200-300ms for natural feel.",
                after_stt_ms,
            )

        m = metrics_ref.get("metrics")
        parsed = parse_breakdown_events(breakdown) if breakdown is not None else {}
        if m:
            m.record_turn(after_stt_ms, parsed)

        # Detailed per-turn latency report and JSONL log
        tracker: LatencyTracker | None = metrics_ref.get("latency_tracker")
        if tracker:
            tracker.record_turn_from_breakdown(after_stt_ms, parsed)

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
    metrics_ref["task"] = task  # so end_call tool can disconnect when user is satisfied

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, webrtc_connection):
        metrics = CallMetrics()
        metrics_ref["metrics"] = metrics
        if not ENABLE_DUAL_LLM:
            metrics.set_model_used(OPENAI_MODEL)

        # Create latency tracker per call (session_id aligned with metrics)
        tracker = LatencyTracker(session_id=metrics.session_id)
        metrics_ref["latency_tracker"] = tracker
        # Push frames through pipeline: latency marker + greeting via TTS (bypasses LLM for consistent intro)
        await task.queue_frames([
            ClientConnectedFrame(),
            TTSSpeakFrame(GREETING_PROMPT, append_to_context=True),
        ])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, webrtc_connection):
        m = metrics_ref.pop("metrics", None)
        tracker: LatencyTracker | None = metrics_ref.pop("latency_tracker", None)
        if m:
            log_and_persist_metrics(m)
            record_feedback(m)
        if tracker:
            tracker.summarize_and_persist()
        await task.cancel()

    # handle_sigint=True so Ctrl+C cancels the pipeline and the process can exit cleanly
    runner = PipelineRunner(handle_sigint=True)
    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Entry point for the Pipecat development runner."""
    if not isinstance(runner_args, SmallWebRTCRunnerArguments):
        raise ValueError("This bot only supports SmallWebRTC. Run with: python -m agent.bot -t webrtc")

    from agent.config import settings
    if not settings.deepgram_api_key or not settings.openai_api_key or not settings.cartesia_api_key:
        raise ValueError("Missing API keys. Set DEEPGRAM_API_KEY, OPENAI_API_KEY, CARTESIA_API_KEY in .env")

    transport, _ = await create_transport(runner_args)
    await run_bot(transport)


if __name__ == "__main__":
    import sys

    from agent.config import settings
    from agent.runner_preflight import apply_runner_argv_from_settings, exit_if_tcp_port_already_listening

    logger.info(
        "[CONFIG] Latency: utterance_end_ms={} endpointing={} model={} tts_low_latency={}",
        settings.deepgram_utterance_end_ms,
        settings.deepgram_endpointing,
        settings.openai_model,
        settings.tts_low_latency,
    )
    apply_runner_argv_from_settings(sys.argv, settings)
    # Resolve effective port from argv for the check
    port = settings.port
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        if i + 1 < len(sys.argv):
            try:
                port = int(sys.argv[i + 1])
            except ValueError:
                pass
    host = settings.host
    if "--host" in sys.argv:
        i = sys.argv.index("--host")
        if i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
    exit_if_tcp_port_already_listening(host, port)
    from pipecat.runner.run import main
    main()

"""
Main Pipecat pipeline for Aria — the AI healthcare receptionist.
Uses SmallWebRTC (peer-to-peer, no API keys) via the development runner.
"""
from agent.config import (
    CARTESIA_API_KEY,
    CARTESIA_VOICE_ID,
    DEEPGRAM_API_KEY,
    DEEPGRAM_ENDPOINTING,
    DEEPGRAM_UTTERANCE_END_MS,
    ENABLE_BACKCHANNELING,
    ENABLE_DUAL_LLM,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_MODEL_FAST,
    GROQ_MODEL_SMART,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    TTS_LOW_LATENCY,
    USE_LLM_CLASSIFIER,
)
from agent.prompts import GREETING_PROMPT, SYSTEM_PROMPT

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import ClientConnectedFrame, TTSSpeakFrame
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy
from pipecat.turns.user_start.transcription_user_turn_start_strategy import TranscriptionUserTurnStartStrategy
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.tts_service import TextAggregationMode
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver

from agent.tools.appointments import (
    book_appointment,
    cancel_appointment,
    check_availability,
    reschedule_appointment,
)
from agent.tools.caller_memory import lookup_caller, save_caller
from agent.tools.clinic_info import get_clinic_info
from agent.tools.escalation import escalate_to_human
from agent.context_manager import ContextTrimmer
from agent.barge_in_logger import BargeInLogger
from agent.emotion_mapper import apply_emotion_transform, EMOTION_CONTENT
from agent.intent_router import IntentRouter
from agent.metrics import CallMetrics, log_and_persist_metrics, parse_breakdown_events

try:
    from deepgram import LiveOptions
except ImportError:
    LiveOptions = None  # type: ignore


def _create_pipeline(transport, metrics_ref: dict):
    """Build the Pipecat pipeline with STT, LLM, TTS, and tools."""
    logger.info(
        "[CONFIG] Latency: utterance_end_ms=%s endpointing=%s model=%s tts_low_latency=%s",
        DEEPGRAM_UTTERANCE_END_MS, DEEPGRAM_ENDPOINTING, GROQ_MODEL, TTS_LOW_LATENCY,
    )
    # STT: use DEEPGRAM_UTTERANCE_END_MS, DEEPGRAM_ENDPOINTING for latency tuning
    stt = DeepgramSTTService(
        api_key=DEEPGRAM_API_KEY,
        **(dict(live_options=LiveOptions(
            model="nova-2",
            language="en",
            encoding="linear16",
            sample_rate=16000,
            channels=1,
            interim_results=True,
            smart_format=True,
            endpointing=DEEPGRAM_ENDPOINTING,
            utterance_end_ms=DEEPGRAM_UTTERANCE_END_MS,
        )) if LiveOptions else {}),
    )

    # Groq: single model or dual (8B/70B routed by IntentRouter)
    initial_model = GROQ_MODEL_FAST if ENABLE_DUAL_LLM else GROQ_MODEL
    llm = GroqLLMService(
        api_key=GROQ_API_KEY,
        settings=GroqLLMService.Settings(
            model=initial_model,
            temperature=LLM_TEMPERATURE,
            max_completion_tokens=LLM_MAX_TOKENS,
        ),
    )

    async def _check_availability(params):
        args = params.arguments
        result = await check_availability(
            args.get("doctor_name_or_specialization", ""),
            args.get("preferred_date", "next available"),
        )
        await params.result_callback(result)

    async def _book_appointment(params):
        args = params.arguments
        result = await book_appointment(
            int(args.get("doctor_id", 0)),
            args.get("patient_name", ""),
            args.get("patient_phone", ""),
            args.get("date", ""),
            args.get("time", ""),
            args.get("notes", ""),
        )
        await params.result_callback(result)

    async def _reschedule_appointment(params):
        args = params.arguments
        result = await reschedule_appointment(
            args.get("appointment_id", ""),
            args.get("new_date", ""),
            args.get("new_time", ""),
        )
        await params.result_callback(result)

    async def _cancel_appointment(params):
        args = params.arguments
        result = await cancel_appointment(
            args.get("appointment_id", ""),
            args.get("reason", ""),
        )
        await params.result_callback(result)

    async def _get_clinic_info(params):
        result = await get_clinic_info(params.arguments.get("topic", "general"))
        await params.result_callback(result)

    async def _lookup_caller(params):
        result = await lookup_caller(params.arguments.get("phone_number", ""))
        m = metrics_ref.get("metrics")
        if m and "Returning caller" in str(result):
            m.set_caller_recognized(True)
        await params.result_callback(result)

    async def _save_caller(params):
        args = params.arguments
        result = await save_caller(
            args.get("phone_number", ""),
            args.get("name", ""),
        )
        await params.result_callback(result)

    async def _escalate_to_human(params):
        args = params.arguments
        reason = args.get("reason", "")
        result = await escalate_to_human(
            reason=reason,
            caller_name=args.get("caller_name", ""),
            caller_phone=args.get("caller_phone", ""),
            caller_wanted=args.get("caller_wanted", ""),
            aria_tried=args.get("aria_tried", ""),
        )
        m = metrics_ref.get("metrics")
        if m:
            m.record_escalation(reason)
        await params.result_callback(result)

    def _wrap_tool_handler(name, handler):
        async def wrapped(params):
            try:
                await handler(params)
                m = metrics_ref.get("metrics")
                if m:
                    m.record_tool_call(name)
            except Exception:
                m = metrics_ref.get("metrics")
                if m:
                    m.record_tool_error()
                raise
        return wrapped

    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema

    tools = ToolsSchema(standard_tools=[
        FunctionSchema(
            name="check_availability",
            description="Check open slots for a doctor by name or specialty",
            properties={
                "doctor_name_or_specialization": {"type": "string", "description": "Doctor name or specialty"},
                "preferred_date": {"type": "string", "description": "YYYY-MM-DD or 'next available'"},
            },
            required=["doctor_name_or_specialization"],
        ),
        FunctionSchema(
            name="book_appointment",
            description="Book appointment with a doctor",
            properties={
                "doctor_id": {"type": "integer", "description": "Doctor ID"},
                "patient_name": {"type": "string", "description": "Patient name"},
                "patient_phone": {"type": "string", "description": "Phone number"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "HH:MM"},
                "notes": {"type": "string", "description": "Optional notes"},
            },
            required=["doctor_id", "patient_name", "patient_phone", "date", "time"],
        ),
        FunctionSchema(
            name="reschedule_appointment",
            description="Reschedule an appointment",
            properties={
                "appointment_id": {"type": "string", "description": "Appointment ID"},
                "new_date": {"type": "string", "description": "New date YYYY-MM-DD"},
                "new_time": {"type": "string", "description": "New time HH:MM"},
            },
            required=["appointment_id", "new_date", "new_time"],
        ),
        FunctionSchema(
            name="cancel_appointment",
            description="Cancel an appointment",
            properties={
                "appointment_id": {"type": "string", "description": "Appointment ID"},
                "reason": {"type": "string", "description": "Optional reason"},
            },
            required=["appointment_id"],
        ),
        FunctionSchema(
            name="get_clinic_info",
            description="Clinic FAQs: hours, address, insurance, services, parking",
            properties={"topic": {"type": "string", "description": "hours, address, insurance, services, parking, general"}},
            required=["topic"],
        ),
        FunctionSchema(
            name="lookup_caller",
            description="Check if caller has called before. Call as soon as you have their phone.",
            properties={"phone_number": {"type": "string", "description": "Phone number"}},
            required=["phone_number"],
        ),
        FunctionSchema(
            name="save_caller",
            description="Save or update caller record when new caller gives name and phone",
            properties={
                "phone_number": {"type": "string", "description": "Phone number"},
                "name": {"type": "string", "description": "Caller name"},
            },
            required=["phone_number"],
        ),
        FunctionSchema(
            name="escalate_to_human",
            description="Transfer to human when user requests, frustrated, failed twice, or out of scope",
            properties={
                "reason": {"type": "string", "description": "Why escalating: user request, frustration, repeated failure, out of scope"},
                "caller_name": {"type": "string", "description": "Caller name if known"},
                "caller_phone": {"type": "string", "description": "Caller phone if known"},
                "caller_wanted": {"type": "string", "description": "What the caller asked for"},
                "aria_tried": {"type": "string", "description": "What Aria already attempted"},
            },
            required=["reason"],
        ),
    ])

    def _wrap_with_metrics(name, fn):
        async def wrapped(params):
            try:
                await fn(params)
                m = metrics_ref.get("metrics")
                if m:
                    m.record_tool_call(name)
            except Exception:
                m = metrics_ref.get("metrics")
                if m:
                    m.record_tool_error()
                raise
        return wrapped

    for name, handler in [
        ("check_availability", _check_availability),
        ("book_appointment", _book_appointment),
        ("reschedule_appointment", _reschedule_appointment),
        ("cancel_appointment", _cancel_appointment),
        ("get_clinic_info", _get_clinic_info),
        ("lookup_caller", _lookup_caller),
        ("save_caller", _save_caller),
        ("escalate_to_human", _escalate_to_human),
    ]:
        llm.register_function(name, _wrap_with_metrics(name, handler))

    context = LLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        tools=tools,
    )

    tts = CartesiaTTSService(
        api_key=CARTESIA_API_KEY,
        text_aggregation_mode=TextAggregationMode.TOKEN if TTS_LOW_LATENCY else TextAggregationMode.SENTENCE,
        settings=CartesiaTTSService.Settings(
            voice=CARTESIA_VOICE_ID,
            generation_config=GenerationConfig(emotion="content", speed=1.05),
        ),
    )

    # Emotion-aware TTS: heuristic infers tone from text, prepends SSML tags (zero latency)
    _last_emotion: list[str] = [EMOTION_CONTENT]
    _last_speed: list[float] = [1.05]

    async def _emotion_transform(text: str, _agg_type: str) -> str:
        out, _, _ = apply_emotion_transform(text, _last_emotion, _last_speed)
        return out

    tts.add_text_transformer(_emotion_transform, "*")

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=UserTurnStrategies(
                start=[
                    VADUserTurnStartStrategy(enable_interruptions=True, enable_user_speaking_frames=True),
                    TranscriptionUserTurnStartStrategy(enable_interruptions=True),
                ],
            ),
        ),
    )

    def _on_barge_in():
        m = metrics_ref.get("metrics")
        if m:
            m.record_barge_in()

    context_trimmer = ContextTrimmer(context)
    barge_in_logger = BargeInLogger(on_barge_in=_on_barge_in)

    # Pipeline: input → STT → user aggregator → ... → LLM → TTS → output
    # TODO (backchanneling): When ENABLE_BACKCHANNELING, add BackchannelProcessor
    # after barge_in_logger to inject "mhm"/"okay" during long user turns. See agent/backchanneling.py.
    pipeline_stages = [
        transport.input(),
        stt,
        user_aggregator,
        barge_in_logger,
        context_trimmer,
    ]
    if ENABLE_DUAL_LLM:
        intent_router = IntentRouter(
            context,
            model_fast=GROQ_MODEL_FAST,
            model_smart=GROQ_MODEL_SMART,
            api_key=GROQ_API_KEY,
            metrics_ref=metrics_ref,
            use_llm_classifier=USE_LLM_CLASSIFIER,
        )
        pipeline_stages.append(intent_router)
    pipeline_stages.extend([llm, tts, transport.output(), assistant_aggregator])

    pipeline = Pipeline(pipeline_stages)
    return pipeline, context


async def _prewarm_db():
    from agent.database.db import get_shared_db
    await get_shared_db()


async def run_bot(transport):
    """Core bot logic — transport-agnostic."""
    await _prewarm_db()
    if ENABLE_BACKCHANNELING:
        logger.warning("[BACKCHANNEL] ENABLE_BACKCHANNELING=true but not implemented; see agent/backchanneling.py TODO")
    metrics_ref = {}
    breakdown_ref = {}
    pipeline, context = _create_pipeline(transport, metrics_ref)

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

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Entry point for the Pipecat development runner."""
    if not isinstance(runner_args, SmallWebRTCRunnerArguments):
        raise ValueError("This bot only supports SmallWebRTC. Run with: python -m agent.bot -t webrtc")

    if not DEEPGRAM_API_KEY or not GROQ_API_KEY or not CARTESIA_API_KEY:
        raise ValueError("Missing API keys. Set DEEPGRAM_API_KEY, GROQ_API_KEY, CARTESIA_API_KEY in .env")

    logger.info(
        "[CONFIG] Latency: utterance_end_ms=%s endpointing=%s model=%s tts_low_latency=%s",
        DEEPGRAM_UTTERANCE_END_MS, DEEPGRAM_ENDPOINTING, GROQ_MODEL, TTS_LOW_LATENCY,
    )

    transport = SmallWebRTCTransport(
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        webrtc_connection=runner_args.webrtc_connection,
    )

    await run_bot(transport)


if __name__ == "__main__":
    # Log loaded latency config so you can verify .env is applied
    logger.info(
        f"[CONFIG] Latency: DEEPGRAM_UTTERANCE_END_MS={DEEPGRAM_UTTERANCE_END_MS}, "
        f"DEEPGRAM_ENDPOINTING={DEEPGRAM_ENDPOINTING}, GROQ_MODEL={GROQ_MODEL}, "
        f"TTS_LOW_LATENCY={TTS_LOW_LATENCY}"
    )
    from pipecat.runner.run import main
    main()

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
    GROQ_API_KEY,
    GROQ_MODEL,
    TTS_LOW_LATENCY,
)
from agent.prompts import GREETING_PROMPT, SYSTEM_PROMPT

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import ClientConnectedFrame, LLMRunFrame
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
from agent.tools.caller_memory import lookup_caller
from agent.tools.clinic_info import get_clinic_info
from agent.tools.escalation import escalate_to_human

try:
    from deepgram import LiveOptions
except ImportError:
    LiveOptions = None  # type: ignore


def _create_pipeline(transport):
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

    # Groq: 70b for accuracy; temperature 0.5 to reduce hallucination
    llm = GroqLLMService(
        api_key=GROQ_API_KEY,
        settings=GroqLLMService.Settings(
            model=GROQ_MODEL,
            temperature=0.5,  # lower = more factual, less creative/hallucinatory
            max_completion_tokens=150,
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
        await params.result_callback(result)

    async def _escalate_to_human(params):
        result = await escalate_to_human(params.arguments.get("reason", ""))
        await params.result_callback(result)

    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema

    tools = ToolsSchema(standard_tools=[
        FunctionSchema(
            name="check_availability",
            description="Check available appointment slots for a doctor by name or specialization",
            properties={
                "doctor_name_or_specialization": {"type": "string", "description": "Doctor name (e.g. Dr. Chen) or specialization (e.g. dermatology)"},
                "preferred_date": {"type": "string", "description": "Date as YYYY-MM-DD or 'next available'"},
            },
            required=["doctor_name_or_specialization"],
        ),
        FunctionSchema(
            name="book_appointment",
            description="Book an appointment with a doctor",
            properties={
                "doctor_id": {"type": "integer", "description": "Doctor ID (1-4)"},
                "patient_name": {"type": "string", "description": "Patient full name"},
                "patient_phone": {"type": "string", "description": "Patient phone number"},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                "time": {"type": "string", "description": "Time as HH:MM or HH:MM:SS"},
                "notes": {"type": "string", "description": "Optional notes"},
            },
            required=["doctor_id", "patient_name", "patient_phone", "date", "time"],
        ),
        FunctionSchema(
            name="reschedule_appointment",
            description="Reschedule an existing appointment",
            properties={
                "appointment_id": {"type": "string", "description": "Appointment ID (e.g. APT-1234)"},
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
            description="Get clinic FAQs: hours, address, insurance, services, parking",
            properties={"topic": {"type": "string", "description": "hours, address, insurance, services, parking, general"}},
            required=["topic"],
        ),
        FunctionSchema(
            name="lookup_caller",
            description="Check if caller has called before (returning caller)",
            properties={"phone_number": {"type": "string", "description": "Caller phone number"}},
            required=["phone_number"],
        ),
        FunctionSchema(
            name="escalate_to_human",
            description="Transfer to human staff when outside Aria's scope",
            properties={"reason": {"type": "string", "description": "Reason for transfer"}},
            required=["reason"],
        ),
    ])

    for name, handler in [
        ("check_availability", _check_availability),
        ("book_appointment", _book_appointment),
        ("reschedule_appointment", _reschedule_appointment),
        ("cancel_appointment", _cancel_appointment),
        ("get_clinic_info", _get_clinic_info),
        ("lookup_caller", _lookup_caller),
        ("escalate_to_human", _escalate_to_human),
    ]:
        llm.register_function(name, handler)

    context = LLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        tools=tools,
    )

    tts = CartesiaTTSService(
        api_key=CARTESIA_API_KEY,
        text_aggregation_mode=TextAggregationMode.TOKEN if TTS_LOW_LATENCY else TextAggregationMode.SENTENCE,
        settings=CartesiaTTSService.Settings(
            voice=CARTESIA_VOICE_ID,
            generation_config=GenerationConfig(
                emotion="content",  # warm, natural tone for humanized voice
                speed=1.0,          # 1.0 for snappier response; 0.95 for more natural pacing
            ),
        ),
    )

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline([
        transport.input(),
        stt,
        user_aggregator,
        llm,
        tts,
        transport.output(),
        assistant_aggregator,
    ])
    return pipeline, context


async def run_bot(transport):
    """Core bot logic — transport-agnostic."""
    pipeline, context = _create_pipeline(transport)

    latency_observer = UserBotLatencyObserver()

    @latency_observer.event_handler("on_first_bot_speech_latency")
    async def _on_first_speech(observer, latency_seconds):
        logger.info(f"[LATENCY] First bot speech (greeting): {latency_seconds:.2f}s")

    @latency_observer.event_handler("on_latency_measured")
    async def _on_latency(observer, latency_seconds):
        logger.info(f"[LATENCY] User→Bot response: {latency_seconds:.2f}s")

    @latency_observer.event_handler("on_latency_breakdown")
    async def _on_breakdown(observer, breakdown):
        logger.info("[LATENCY] Breakdown:")
        for event in breakdown.chronological_events():
            logger.info(f"  {event}")

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
        # Push ClientConnectedFrame so latency observer can measure first speech
        await task.queue_frames([ClientConnectedFrame()])
        context.add_message({"role": "user", "content": f"Greet the caller. Say: {GREETING_PROMPT}"})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, webrtc_connection):
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

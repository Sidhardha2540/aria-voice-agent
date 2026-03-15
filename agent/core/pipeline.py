"""
Pipeline builder — STT, LLM, TTS, and tools.
Transport-agnostic: receives transport from the factory, never imports a specific transport.
"""
from agent.config import (
    CARTESIA_API_KEY,
    CARTESIA_VOICE_ID,
    DEEPGRAM_API_KEY,
    DEEPGRAM_ENDPOINTING,
    DEEPGRAM_UTTERANCE_END_MS,
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
from agent.prompts import GREETING_PROMPT, get_system_prompt
from agent.tools.handlers import create_tool_handlers
from agent.tools.registry import get_tool_schemas
from agent.context_manager import ContextTrimmer
from agent.barge_in_logger import BargeInLogger
from agent.processors.function_call_filter import FunctionCallFilter
from agent.emotion_mapper import EMOTION_CONTENT, apply_emotion_transform
from agent.intent_router import IntentRouter
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.tts_service import TextAggregationMode
from pipecat.turns.user_start.transcription_user_turn_start_strategy import (
    TranscriptionUserTurnStartStrategy,
)
from pipecat.turns.user_start.vad_user_turn_start_strategy import VADUserTurnStartStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

try:
    from deepgram import LiveOptions
except ImportError:
    LiveOptions = None  # type: ignore


def create_pipeline(transport, metrics_ref: dict):
    """Build the Pipecat pipeline with STT, LLM, TTS, and tools. Returns (pipeline, context)."""
    logger.info(
        "[CONFIG] Latency: utterance_end_ms=%s endpointing=%s model=%s tts_low_latency=%s",
        DEEPGRAM_UTTERANCE_END_MS,
        DEEPGRAM_ENDPOINTING,
        GROQ_MODEL,
        TTS_LOW_LATENCY,
    )

    stt = DeepgramSTTService(
        api_key=DEEPGRAM_API_KEY,
        **(
            dict(
                live_options=LiveOptions(
                    model="nova-2",
                    language="en",
                    encoding="linear16",
                    sample_rate=16000,
                    channels=1,
                    interim_results=True,
                    smart_format=True,
                    endpointing=DEEPGRAM_ENDPOINTING,
                    utterance_end_ms=DEEPGRAM_UTTERANCE_END_MS,
                )
            )
            if LiveOptions
            else {}
        ),
    )

    initial_model = GROQ_MODEL_FAST if ENABLE_DUAL_LLM else GROQ_MODEL
    llm = GroqLLMService(
        api_key=GROQ_API_KEY,
        settings=GroqLLMService.Settings(
            model=initial_model,
            temperature=LLM_TEMPERATURE,
            max_completion_tokens=LLM_MAX_TOKENS,
        ),
    )

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

    tools = get_tool_schemas()
    tool_handlers = create_tool_handlers(
        session_id=metrics_ref.get("session_id", "unknown"),
        metrics_ref=metrics_ref,
    )
    for name, handler in tool_handlers.items():
        llm.register_function(name, _wrap_with_metrics(name, handler))

    context = LLMContext(
        messages=[{"role": "system", "content": get_system_prompt()}],
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
                    VADUserTurnStartStrategy(
                        enable_interruptions=True,
                        enable_user_speaking_frames=True,
                    ),
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
    # Filter strips < function = ... >{...}</ function > from LLM output so TTS doesn't speak it
    pipeline_stages.extend([llm, FunctionCallFilter(), tts, transport.output(), assistant_aggregator])

    pipeline = Pipeline(pipeline_stages)
    return pipeline, context

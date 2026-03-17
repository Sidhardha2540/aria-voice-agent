"""
Intent-based LLM routing — simple queries → 8B, complex → 70B.
Option A: 8B classifier (~50ms). Option B: keyword matching (zero latency).
"""
import asyncio
import re
from typing import Literal

from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor

Intent = Literal["simple", "complex"]

# SIMPLE: FAQs, yes/no, greetings, single-step clear actions
_SIMPLE_FAQ = re.compile(
    r"\b(hours?|open|close|address|where are you|insurance|parking|services|"
    r"phone number|contact)\b",
    re.I,
)
_SIMPLE_YES_NO = re.compile(
    r"^(yes|no|yeah|nope|correct|right|yep|sure|okay|ok|book it|go ahead|"
    r"cancel it|do it|that's right|exactly|perfect)\s*[.!?]?$",
    re.I,
)
_SIMPLE_GREETING = re.compile(
    r"^(hi|hello|hey|thanks|thank you|good morning|good afternoon|good evening)\s*[.!?]?$",
    re.I,
)
_SIMPLE_SINGLE = re.compile(
    r"\b(cancel\s+my\s+appointment|what\s+are\s+your\s+hours|do\s+you\s+take\s+"
    r"(insurance|my\s+insurance)|where\s+(is|are)\s+you|parking)\b",
    re.I,
)

# COMPLEX: multi-constraint, ambiguous, frustration, error recovery
_COMPLEX_MULTI = re.compile(
    r"\b(morning|afternoon|evening|next\s+week|not\s+monday|but\s+not|"
    r"sometime\s+after|when\s+(dr|doctor)|available)\b.*\b(and|but|or|when)\b",
    re.I | re.S,
)
_COMPLEX_AMBIGUOUS = re.compile(
    r"\b(not\s+sure|which\s+doctor|don't\s+know|unsure|either|either\s+or)\b",
    re.I,
)
_COMPLEX_FRUSTRATION = re.compile(
    r"\b(frustrat|confused|isn't\s+working|said\s+(this|that)\s+\d|"
    r"not\s+listening|wrong|again)\b",
    re.I,
)


def classify_by_keywords(text: str, previous_turn_had_error: bool = False) -> Intent:
    """
    Option B: Zero-latency keyword/pattern matching.
    Returns "simple" for FAQs, yes/no, greetings, single-step; "complex" otherwise.
    """
    if not text or not text.strip():
        return "simple"

    msg = text.strip()
    lower = msg.lower()
    words = len(lower.split())

    # Hard COMPLEX signals
    if previous_turn_had_error:
        return "complex"
    if _COMPLEX_FRUSTRATION.search(msg):
        return "complex"
    if _COMPLEX_AMBIGUOUS.search(msg):
        return "complex"
    if _COMPLEX_MULTI.search(msg):
        return "complex"

    # Hard SIMPLE signals (short + matches)
    if words <= 5 and _SIMPLE_YES_NO.search(msg):
        return "simple"
    if words <= 6 and _SIMPLE_GREETING.search(msg):
        return "simple"
    if words <= 12 and _SIMPLE_FAQ.search(msg):
        return "simple"
    if words <= 10 and _SIMPLE_SINGLE.search(msg):
        return "simple"

    # Rescheduling / multi-step tends to be complex
    if re.search(r"\breschedul", lower) and words > 8:
        return "complex"

    # Short messages: likely simple (yes/no, thanks, etc.)
    if words <= 4:
        return "simple"

    # Default: longer or unclear → complex (safe choice)
    return "complex"


def _sync_classify_by_llm(text: str, api_key: str, model_fast: str) -> Intent:
    """Sync OpenAI call — run via executor to avoid blocking event loop."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    prompt = f'Classify as SIMPLE or COMPLEX. Reply with only one word.\nUser: "{text[:200]}"'
    resp = client.chat.completions.create(
        model=model_fast,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=5,
        temperature=0,
    )
    out = (resp.choices[0].message.content or "").strip().upper()
    return "complex" if "COMPLEX" in out else "simple"


async def classify_by_llm(
    text: str,
    api_key: str,
    model_fast: str,
    previous_turn_had_error: bool = False,
    timeout_ms: int = 70,
) -> Intent:
    """
    Option A: Use 8B as pre-classifier. Adds ~50ms but more accurate.
    Runs sync Groq call in executor to avoid blocking.
    """
    if previous_turn_had_error:
        return "complex"

    try:
        loop = asyncio.get_event_loop()
        intent = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _sync_classify_by_llm(text, api_key, model_fast),
            ),
            timeout=timeout_ms / 1000.0,
        )
        return intent
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning("LLM classifier failed, falling back to keywords: %s", e)
        return classify_by_keywords(text, previous_turn_had_error)


class IntentRouter(FrameProcessor):
    """
    FrameProcessor that routes to 8B or 70B based on user message complexity.
    Sits between context_trimmer and LLM; pushes LLMUpdateSettingsFrame before each run.
    """

    def __init__(
        self,
        context: "LLMContext",
        model_fast: str,
        model_smart: str,
        api_key: str,
        metrics_ref: dict,
        use_llm_classifier: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._context = context
        self._model_fast = model_fast
        self._model_smart = model_smart
        self._api_key = api_key
        self._metrics_ref = metrics_ref
        self._use_llm_classifier = use_llm_classifier
        self._last_classified_content: str | None = None

    async def process_frame(self, frame, direction):
        from pipecat.frames.frames import LLMUpdateSettingsFrame
        from pipecat.services.openai.llm import OpenAILLMService

        await super().process_frame(frame, direction)

        # Get last user message from context
        messages = self._context.messages
        last_user = None
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                last_user = m.get("content") or ""
                break

        if last_user is not None and last_user != self._last_classified_content:
            self._last_classified_content = last_user
            if self._use_llm_classifier:
                intent = await classify_by_llm(
                    last_user, self._api_key, self._model_fast, timeout_ms=70
                )
            else:
                intent = classify_by_keywords(last_user)

            model = self._model_fast if intent == "simple" else self._model_smart
            label = "gpt-4o-mini" if "mini" in model else "gpt-4o"
            logger.info("[LLM] Model: %s (%s)", label, intent)

            m = self._metrics_ref.get("metrics")
            if m:
                m.set_model_used(label)

            await self.push_frame(
                LLMUpdateSettingsFrame(settings=OpenAILLMService.Settings(model=model)),
                direction,
            )

        await self.push_frame(frame, direction)

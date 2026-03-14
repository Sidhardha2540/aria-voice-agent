"""
Emotion mapping for TTS — infers emotional tone from text.
Uses keyword heuristics; maps to Cartesia-supported emotions.
Zero latency: simple string checks, no buffering.
"""

# Cartesia-supported emotions for our response types
# https://docs.cartesia.ai/build-with-cartesia/sonic-3/volume-speed-emotion
EMOTION_CONTENT = "content"      # neutral, clear
EMOTION_HAPPY = "happy"           # upbeat, positive
EMOTION_AFFECTIONATE = "affectionate"  # warm, friendly
EMOTION_SYMPATHETIC = "sympathetic"    # empathetic, gentle
EMOTION_APOLOGETIC = "apologetic"       # sincere, sorry
EMOTION_CALM = "calm"             # reassuring


def infer_emotion_and_speed(text: str) -> tuple[str, float]:
    """
    Infer emotion and speed from text using keyword heuristics.
    Returns (emotion, speed) where speed is 0.8–1.15.
    """
    if not text or not text.strip():
        return EMOTION_CONTENT, 1.05

    lower = text.lower().strip()

    # Escalating / transfer → calm, reassuring (slightly slower)
    if any(w in lower for w in ("connect you", "front desk", "transfer", "pass along", "right help")):
        return EMOTION_CALM, 0.95

    # Apologizing / can't help → sympathetic or apologetic
    if any(w in lower for w in ("sorry", "apolog", "unfortunately", "afraid i", "can't help", "couldn't find")):
        return EMOTION_APOLOGETIC, 0.9

    # Bad news / no slots → sympathetic
    if any(w in lower for w in ("no slots", "not available", "don't have", "aren't available", "fully booked")):
        return EMOTION_SYMPATHETIC, 0.92

    # Confirming booking / success → happy, upbeat
    if any(w in lower for w in ("booked", "confirmed", "you're scheduled", "all set", "you're all set")):
        return EMOTION_HAPPY, 1.08

    # Greeting / welcome back → warm, friendly
    if any(w in lower for w in ("welcome back", "great to hear", "hi ", "hello ", "thanks for calling", "how can i help")):
        return EMOTION_AFFECTIONATE, 1.02

    # Reading back details / confirmation prompt → neutral, clear
    if any(w in lower for w in ("just to confirm", "that's ", "is that correct", "should i go ahead", "go ahead and")):
        return EMOTION_CONTENT, 1.0

    # Default
    return EMOTION_CONTENT, 1.05


def make_emotion_tag(emotion: str) -> str:
    """Cartesia SSML emotion tag (self-closing)."""
    return f'<emotion value="{emotion}" />'


def apply_emotion_transform(
    text: str,
    last_emotion: list[str],
    last_speed: list[float],
    base_emotion: str = EMOTION_CONTENT,
    base_speed: float = 1.05,
) -> tuple[str, str, float]:
    """
    Transform text with emotion/speed tags when heuristic detects a change.
    Uses mutable lists for last_emotion, last_speed to maintain state across calls.
    Returns (transformed_text, new_emotion, new_speed).
    """
    emotion, speed = infer_emotion_and_speed(text)
    new_emotion = last_emotion[0]
    new_speed = last_speed[0]

    out = text
    if emotion != last_emotion[0] and text.strip():
        tag = make_emotion_tag(emotion)
        out = f"{tag} {text}"
        last_emotion[0] = emotion
        new_emotion = emotion

    # Cartesia speed tag when we want slower (empathetic) or faster (confirmations)
    if abs(speed - base_speed) > 0.03 and speed != last_speed[0]:
        # Only add speed tag for notable changes; Cartesia uses <speed ratio="X"/>
        speed_tag = f'<speed ratio="{speed:.2f}" />'
        if not out.startswith("<"):
            out = f"{speed_tag} {out}"
        elif " />" in out:
            # Already have emotion tag; prepend speed before emotion
            out = f"{speed_tag} {out}"
        last_speed[0] = speed
        new_speed = speed

    return out, new_emotion, new_speed

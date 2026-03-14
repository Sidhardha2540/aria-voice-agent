"""
Backchanneling — subtle acknowledgments ("mhm", "okay") during long user turns.

TODO: NOT YET IMPLEMENTED. This module documents the approach for future implementation.

Problem:
When a user gives a long explanation (e.g. "So I need to reschedule because my work
schedule changed and I was thinking maybe next week..."), Aria is silent until they
stop. This feels like talking to a void.

Desired behavior:
- During longer user turns (3+ seconds of continuous speech), inject ONE short
  acknowledgment: "mhm", "okay", "got it", "right", or "I see"
- Trigger only after a brief natural pause (200–500ms) — not enough to endpoint
- Pre-generated audio (<0.5s) to avoid TTS latency
- Must NOT trigger turn release; must NOT interrupt STT
- Toggle: ENABLE_BACKCHANNELING=true (default false)

Implementation approach (when tackling this):

1. VAD monitoring
   - Pipecat's Silero VAD lives inside LLMUserAggregatorParams; it emits
     UserStartedSpeakingFrame / UserStoppedSpeakingFrame at turn boundaries.
   - We need finer granularity: "user has been speaking 3+ s with a 200–500ms pause".
   - Options:
     a) Add a processor that receives UserSpeakingFrame (if available) or raw
        audio/VAD events and tracks speech duration + pause detection.
     b) Use transcription-based heuristic: if interim transcripts show >3s of
        content with a gap in updates (200–500ms), infer a brief pause.
     c) Extend or wrap the VAD analyzer to emit segment-level events (more invasive).

2. Pre-generated audio
   - At startup (or first use): call Cartesia TTS for each phrase
     ("mhm", "okay", "got it", "right", "I see"), store raw PCM bytes.
   - Use the same voice/sample_rate as the main TTS for consistency.
   - Cache in memory; keep clips under ~0.5s.

3. Output injection
   - To play audio to the user during their speech, we must push frames that
     reach transport.output().
   - Options:
     a) Use task.queue_frames([OutputAudioRawFrame(...)]) from a processor or
        callback that has access to the PipelineTask. Need to verify routing.
     b) Add a BackchannelProcessor that sits in the pipeline and can push
        audio frames downstream. Placement matters: frames must flow to output
        without being blocked by LLM/TTS. May require a tee or a processor
        that wraps transport.output() and can inject.
     c) Use a transport-level callback (if SmallWebRTCTransport supports
        injecting audio into the outbound stream).

4. State machine
   - Track: user_speech_started_at, last_interim_at, backchannel_sent_this_turn.
   - On "3+ s of speech AND 200–500ms pause AND not yet sent backchannel":
     choose random phrase, push cached audio, set backchannel_sent_this_turn=True.
   - Reset backchannel_sent_this_turn when user turn fully ends (turn release).

5. Risks / mitigations
   - Overlap with Aria response: only trigger when bot is NOT speaking.
   - Pipeline complexity: keep logic minimal; prefer not implementing over a
     fragile or high-latency solution.
   - If adding >50ms latency or risking turn-release bugs, skip entirely.

Files to modify when implementing:
- agent/bot.py: wire BackchannelProcessor (when ENABLE_BACKCHANNELING)
- agent/config.py: ENABLE_BACKCHANNELING (already added)
"""

BACKCHANNEL_PHRASES = ["mhm", "okay", "got it", "right", "I see"]

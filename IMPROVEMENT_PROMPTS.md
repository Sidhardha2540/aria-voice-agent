# Aria Voice Agent — Cursor Prompts for Improvements

Use these prompts one by one in Cursor. Each prompt is a self-contained task. Go in order — they build on each other.

---

## Prompt 1: Interruption Handling (Barge-in)

```
I need to add proper interruption/barge-in handling to my Aria voice agent built with Pipecat.

Current setup:
- Pipecat pipeline with SmallWebRTC transport
- Deepgram STT → Groq LLM → Cartesia TTS
- Silero VAD for voice activity detection
- Main pipeline is in agent/bot.py

What I want:
When the user starts speaking while Aria is still talking, Aria should:
1. Immediately stop its current audio output (cancel TTS)
2. Discard any unspoken queued text
3. Listen to the user's new input
4. Respond to what the user just said, not continue the old response

Implementation requirements:
- Listen for UserStartedSpeakingFrame in the pipeline
- When detected during bot speech, cancel the current LLM generation and TTS output
- Make sure the conversation context is updated correctly (don't lose track of what was already said vs what was cut off)
- The transition should feel smooth — no audio glitches or doubled responses
- Add a log line: [BARGE-IN] User interrupted bot at {timestamp}

Look at Pipecat's built-in interruption handling mechanisms first. Pipecat may already support this via pipeline configuration or frame handling. Use the framework's native approach rather than building custom logic.

Do NOT change the existing latency optimizations (utterance_end_ms, endpointing, token TTS mode, etc).
```

---

## Prompt 2: Filler Phrases During Tool Calls

```
I need to add filler phrases that play BEFORE tool calls in my Aria voice agent.

Current problem:
When the user asks to book an appointment, there's a silence gap while the LLM calls check_availability, waits for the result, then calls book_appointment. The user hears dead air.

What I want:
Before any tool call, Aria should say a short filler phrase like:
- "Sure, let me check that for you."
- "One moment, I'll look that up."
- "Let me pull that up."
- "Checking now..."

The filler audio should play WHILE the tool executes in the background, not before it.

Implementation approach:
Option A (preferred — prompt-level): Update the system prompt in agent/prompts.py to instruct the LLM to always emit a short filler sentence before calling any tool. The LLM should output the filler text first (which goes to TTS immediately via token streaming), then make the tool call. This way TTS starts speaking the filler while the tool executes.

Option B (code-level fallback): If Option A doesn't work reliably with Groq/Llama, add a ToolCallFillerProcessor in the Pipecat pipeline that intercepts tool call frames, injects a random filler phrase into TTS, and then lets the tool call proceed in parallel.

Requirements:
- Filler phrases should be varied (rotate through a list, don't repeat the same one every time)
- Filler should only play for tools that involve a DB lookup or external call (check_availability, book_appointment, reschedule_appointment, cancel_appointment, lookup_caller). NOT for get_clinic_info since that's cached and instant.
- The filler must NOT delay the tool call — they should happen in parallel
- Keep filler phrases short (under 8 words)
- Add the filler phrase list in agent/prompts.py

Files to modify: agent/prompts.py, possibly agent/bot.py
```

---

## Prompt 3: Confirmation Before Destructive Actions

```
I need to add a confirmation step before Aria executes booking, rescheduling, or cancellation actions.

Current problem:
If the user says "book me with Dr. Patel on Thursday at 2pm", Aria calls book_appointment immediately. If STT misheard "Thursday" as "Tuesday", the wrong appointment gets booked silently.

What I want:
Before calling book_appointment, reschedule_appointment, or cancel_appointment, Aria should read back the details and ask for confirmation:

For booking:
"Just to confirm — that's an appointment with Dr. Patel on Thursday, March 19th at 2:00 PM, under the name [patient name]. Should I go ahead and book that?"

For rescheduling:
"So you'd like to move your appointment from [old date/time] to [new date/time] with Dr. [name]. Is that correct?"

For cancellation:
"You'd like to cancel your appointment with Dr. [name] on [date] at [time]. Are you sure?"

Only after the user says yes/confirm/correct/go ahead should the tool actually execute.

Implementation:
- This should be handled in the system prompt (agent/prompts.py) by instructing the LLM to always confirm before calling book/reschedule/cancel tools
- The LLM should first call check_availability to verify the slot, then present the confirmation, then only call book_appointment after user confirms
- If the user says "no" or corrects something, Aria should ask what they'd like to change
- check_availability and get_clinic_info do NOT need confirmation (they're read-only)
- lookup_caller does NOT need confirmation

Update the system prompt with clear instructions and examples of the confirmation flow.
File: agent/prompts.py
```

---

## Prompt 4: Graceful Error Recovery & Clarification

```
I need Aria to gracefully handle STT errors and ambiguous input instead of failing silently.

Current problem:
If Deepgram mishears a doctor name, date, or time, Aria either:
- Tries to book with wrong info and fails
- Says something generic and unhelpful
- Calls a tool with bad data and gets an error

What I want — smart recovery in these scenarios:

1. Unknown doctor name:
   User says "Dr. Patel" but STT hears "Dr. Patal"
   → Aria should check available doctors and suggest closest matches:
   "I didn't find a Dr. Patal. We have Dr. Patel and Dr. Patani. Which one did you mean?"

2. Invalid date/time:
   User says "next Saturday" but clinic is closed on weekends
   → "Our clinic isn't open on Saturdays. Would you like to book for Friday the 21st or Monday the 24th instead?"

3. Ambiguous input:
   User says "I need to see someone about my back"
   → "We have Dr. Patel who specializes in orthopedics and Dr. Singh in physiotherapy. Which would you prefer?"

4. Tool call returns an error or empty result:
   check_availability returns no slots
   → "Dr. Patel doesn't have any openings on Thursday. Would you like me to check Friday, or would you prefer a different doctor?"

Implementation:
- Update the system prompt in agent/prompts.py with recovery instructions and examples
- Add fuzzy matching logic in agent/tools/appointments.py — when check_availability or book_appointment gets a doctor name that doesn't match exactly, return the closest matches from the doctors table instead of just failing
- Use SQLite LIKE queries or simple string similarity to find close matches
- The LLM should be instructed to NEVER say "I couldn't find that" without offering alternatives
- Always give the user 2-3 options to choose from when something is ambiguous

Files: agent/prompts.py, agent/tools/appointments.py
```

---

## Prompt 5: Returning Caller Personalization

```
I need to make Aria use the existing caller memory system more aggressively for personalization.

Current setup:
- callers table exists with: phone_number, name, last_call_at, preferences, call_count
- lookup_caller tool exists in agent/tools/caller_memory.py
- But it's barely used — Aria treats every caller the same

What I want:

1. At the START of every call, Aria should call lookup_caller automatically (not wait for the user to identify themselves). In the greeting flow, after the initial "Hello, thanks for calling...", Aria should check if the caller is known.

2. For returning callers:
   - Greet them by name: "Welcome back, Rahul!"
   - Reference their history: "Last time you saw Dr. Patel. Would you like to book with her again?"
   - If they have preferences stored, use them proactively

3. For new callers:
   - Ask for their name early in the conversation
   - Save their info to the callers table after the call (name, preferences, etc.)

4. After every successful booking, update the caller record:
   - Increment call_count
   - Update last_call_at
   - Store the doctor they booked with in preferences

Implementation:
- Update agent/prompts.py to include caller memory instructions in the system prompt
- Update agent/tools/caller_memory.py to add an update_caller or save_caller_preference tool
- Add a new tool: save_caller that creates/updates caller records
- The LLM should call lookup_caller as its FIRST action, using caller ID from the transport/session if available
- If no caller ID is available (WebRTC), Aria should ask "May I have your name and phone number?" early in the conversation

Files: agent/prompts.py, agent/tools/caller_memory.py
```

---

## Prompt 6: Prosody/Emotion Switching in TTS

```
I need Aria to use different emotional tones for different types of responses, using Cartesia's emotion controls.

Current setup:
- Cartesia Sonic-3 TTS with a fixed emotion="content" and speed=1.05
- Config in agent/bot.py → CartesiaTTSService

What I want:
Different response types should have different emotional delivery:

1. Greeting / Welcome back → warm, friendly (emotion: "friendly", "warm")
2. Confirming a booking → upbeat, positive (emotion: "happy", "satisfied")
3. Slot not available / bad news → empathetic, gentle (emotion: "empathetic", "calm")
4. Reading back details / confirmation → neutral, clear (emotion: "content")
5. Apologizing / can't help → sincere, slightly apologetic (emotion: "empathetic")
6. Escalating to human → reassuring (emotion: "calm", "reassuring")

Implementation approach:
- Check if Cartesia's API supports per-request or per-sentence emotion parameters
- If Cartesia supports SSML-style emotion tags or API-level emotion params per synthesis call, use that
- Option A: Have the LLM output emotion hints in a structured format like [EMOTION:happy] before each sentence, then strip the tag and pass the emotion to Cartesia
- Option B: Use a simple heuristic — detect keywords in the LLM output (e.g., "sorry", "unfortunately" → empathetic; "booked", "confirmed" → happy) and set emotion accordingly
- Option C: If Cartesia doesn't support dynamic emotion switching, at minimum vary the speed — slightly slower for empathetic moments, slightly faster for confirmations

Requirements:
- The emotion switching should not add latency
- Don't break the existing token streaming mode
- Keep it simple — even 2-3 emotion modes (positive, neutral, empathetic) would be a big improvement over one fixed tone

Files: agent/bot.py, possibly a new agent/emotion_mapper.py
```

---

## Prompt 7: Backchanneling ("mhm", "got it")

```
I need Aria to produce subtle acknowledgment sounds while the user is speaking, like a real receptionist would.

Current problem:
When a user is giving a long explanation ("So I need to reschedule my appointment because my work schedule changed and I was thinking maybe next week would work better..."), Aria is completely silent until they stop. This feels like talking to a void.

What I want:
During longer user turns, Aria should inject very short acknowledgments:
- "mhm"
- "okay"  
- "got it"
- "right"
- "I see"

Rules:
- Only trigger after the user has been speaking for 3+ seconds continuously
- Only inject ONE backchannel per long user turn (don't spam them)
- The backchannel should be very quick (under 0.5s of audio)
- It should NOT trigger turn release — Aria should keep listening after the backchannel
- It should NOT interrupt the STT processing of the user's speech
- Backchanneling is LOW priority — if it adds complexity or latency, skip it entirely

Implementation:
- This needs a custom processor in the Pipecat pipeline that monitors VAD
- When VAD shows continuous speech for 3+ seconds with a brief natural pause (200-500ms, detected by VAD but not long enough for endpointing), inject a short TTS phrase
- The backchannel audio should be pre-generated (not real-time TTS) to avoid latency — generate the audio clips at startup and cache them
- Make this feature toggleable via an env var: ENABLE_BACKCHANNELING=true/false (default false)

This is an advanced feature. If the implementation is too complex or risky for the pipeline stability, just add a TODO comment explaining the approach and skip the implementation.

Files: agent/bot.py, possibly new agent/backchanneling.py
```

---

## Prompt 8: Dual LLM Strategy (Fast + Smart Routing)

```
I need to implement intent-based LLM routing so simple queries use the fast 8B model and complex queries use the 70B model.

Current setup:
- Single LLM: Groq llama-3.1-8b-instant for everything
- Config in agent/bot.py → GroqLLMService

Problem:
8B handles "what are your hours?" perfectly but struggles with complex multi-step rescheduling, edge cases, or ambiguous requests.

What I want:
Route to different models based on the complexity of the user's request:

FAST model (8B-instant) for:
- Simple FAQs: hours, address, insurance, parking, services
- Yes/no confirmations: "yes book it", "no", "correct"
- Simple greetings: "hi", "hello", "thanks"
- Single-step actions with clear intent: "cancel my appointment"

SMART model (70B-versatile) for:
- Multi-constraint scheduling: "I need a morning slot with Dr. Patel next week but not Monday"
- Rescheduling with conditions: "move it to sometime after 3pm on a day when Dr. Singh is available"
- Ambiguous or complex queries: "I'm not sure which doctor I need..."
- Error recovery: when the previous turn had a misunderstanding
- Any turn where the user expresses confusion or frustration

Implementation approach:
- Add a lightweight intent classifier BEFORE the main LLM call
- Option A (preferred): Use the 8B model itself as a pre-classifier — send a very short prompt like "Classify this user message as SIMPLE or COMPLEX: '{user_message}'" and route based on the result. This adds ~50ms but saves ~150ms on simple turns (net gain).
- Option B: Use keyword/pattern matching — if the message is under 10 words and matches common patterns (FAQ keywords, yes/no, greetings), use 8B. Otherwise use 70B. No latency cost but less accurate.
- Option C: Default to 8B, but if the tool call fails or the response seems low-confidence, retry with 70B.

Requirements:
- Add env vars: GROQ_MODEL_FAST=llama-3.1-8b-instant, GROQ_MODEL_SMART=llama-3.3-70b-versatile
- Log which model was used per turn: [LLM] Model: 8b-instant (simple) or [LLM] Model: 70b (complex)
- The routing should NOT add more than 80ms of latency
- Both models should use the same system prompt and tools
- Make this toggleable: ENABLE_DUAL_LLM=true/false (default false, uses single model)

Files: agent/bot.py, agent/config.py, possibly new agent/intent_router.py
```

---

## Prompt 9: Graceful Escalation with Context Handoff

```
I need to improve Aria's escalation flow when transferring to a human agent.

Current setup:
- escalate_to_human tool exists in agent/tools/escalation.py
- It just logs the reason — no real handoff happens

What I want:

1. Better escalation triggers — Aria should escalate when:
   - User explicitly asks for a human: "let me talk to someone", "transfer me"
   - User expresses frustration: "this isn't working", "I've said this 3 times"
   - Aria fails the same task twice in a row
   - The request is out of scope (insurance claims, billing disputes, medical questions)

2. Warm handoff message to the user:
   "I want to make sure you get the right help. Let me connect you with our front desk team. I'll pass along what we've discussed so you won't have to repeat yourself."

3. Context summary for the human agent — when escalate_to_human is called, generate and log a summary:
   - Caller name and phone (if known)
   - What the caller wanted
   - What Aria already tried/accomplished
   - Why escalation was triggered
   - Format as a clean JSON object

4. Frustration detection:
   - Track a simple frustration_score in the conversation
   - If the user repeats themselves, uses negative language, or raises voice (detectable via STT confidence drops or specific phrases), increment the score
   - Auto-escalate if frustration_score exceeds threshold

Implementation:
- Update agent/prompts.py with escalation rules and the warm handoff script
- Update agent/tools/escalation.py to generate the context summary
- Add frustration tracking — either in the system prompt (have the LLM self-assess) or as a simple keyword detector
- Log the full context summary as: [ESCALATION] Reason: {reason}, Summary: {json}

Files: agent/prompts.py, agent/tools/escalation.py
```

---

## Prompt 10: Conversation Analytics & Metrics Logging

```
I need comprehensive per-call metrics logging so I can measure voice agent quality.

Current setup:
- UserBotLatencyObserver logs latency per turn
- Basic loguru logging

What I want — a structured metrics log for EVERY call that captures:

1. Latency metrics (per turn):
   - user_turn_duration_ms (how long user spoke)
   - stt_time_ms (Deepgram processing)
   - llm_ttfb_ms (time to first token from Groq)
   - tts_ttfb_ms (time to first audio from Cartesia)
   - total_response_ms (user stops → bot starts)
   - tool_call_duration_ms (if applicable)

2. Conversation metrics (per call):
   - total_turns (number of user-bot exchanges)
   - total_call_duration_s
   - task_completed (boolean — did the user accomplish their goal?)
   - task_type (booking, rescheduling, cancellation, faq, escalation)
   - escalated (boolean)
   - escalation_reason (if applicable)
   - interruptions_count (number of barge-ins)

3. Quality metrics (per call):
   - tools_called (list of tool names used)
   - tool_errors (count of failed tool calls)
   - model_used (8b or 70b, if dual LLM is enabled)
   - caller_recognized (boolean — returning caller?)
   - confirmation_accepted_first_try (boolean)

Output format:
- Log a single JSON object at the end of each call: [CALL_METRICS] {json}
- Also write to a metrics file: data/metrics.jsonl (one JSON per line, append mode)
- Include a session_id and timestamp

Implementation:
- Create agent/metrics.py with a CallMetrics class that accumulates data during the call
- Hook it into the pipeline processors to capture timing data
- At call end (transport disconnect), write the final metrics
- Make sure metrics collection adds ZERO latency to the pipeline (async writes only)

Files: new agent/metrics.py, agent/bot.py
```

---

## Usage Order

Recommended implementation order (highest impact first):

1. **Prompt 2** — Filler phrases (quick win, biggest UX improvement)
2. **Prompt 3** — Confirmation before actions (prevents bad bookings)
3. **Prompt 4** — Error recovery (handles STT mistakes gracefully)
4. **Prompt 1** — Interruption handling (makes it feel real)
5. **Prompt 9** — Graceful escalation (safety net)
6. **Prompt 5** — Caller personalization (wow factor)
7. **Prompt 10** — Metrics logging (measure everything)
8. **Prompt 6** — Emotion switching (polish)
9. **Prompt 8** — Dual LLM routing (optimization)
10. **Prompt 7** — Backchanneling (advanced, optional)

---

*Each prompt is self-contained. Copy-paste one at a time into Cursor. Let Cursor implement it, test it, then move to the next.*

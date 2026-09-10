# Provider Troubleshooting

Aria depends on separate services for speech recognition, conversation, and speech generation. Use this guide to narrow failures by provider.

## Deepgram

- Check `DEEPGRAM_API_KEY` first when the bot hears audio but produces no transcript.
- Confirm the selected model supports streaming.
- Review endpointing settings when phrases are cut off early or delayed too long.
- Compare microphone input in the browser with server-side transcript logs.

## OpenAI

- Check `OPENAI_API_KEY` when transcripts appear but no assistant response is generated.
- Confirm `OPENAI_MODEL` points to a model that supports tool calling.
- Inspect tool-call arguments before changing appointment or escalation code.
- Keep prompts concise when latency rises during long conversations.

## Cartesia

- Check `CARTESIA_API_KEY` when text responses appear but no audio plays.
- Confirm the configured voice is available to the account.
- Toggle low-latency settings only after confirming the rest of the pipeline works.
- Listen for clipped responses after changing sentence or token streaming behavior.

## Cross-provider Symptoms

- If every turn is slow, compare network latency with provider response timing.
- If only first turns are slow, check startup initialization and connection warmup.
- If failures happen after several minutes, inspect session cleanup and retry behavior.
- If one provider is temporarily unavailable, capture a sanitized log excerpt and retry after a short delay.

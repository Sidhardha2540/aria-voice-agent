# Pipeline diagnostics — find where it breaks

## Which LLM is used?

**OpenAI only.** The app uses:

- **Config:** `agent/config.py` — `openai_api_key` (required), `openai_model` (default `gpt-4o-mini`).
- **Pipeline:** `agent/core/pipeline.py` — `OpenAILLMService` from Pipecat, no Groq.
- **Intent router (if ENABLE_DUAL_LLM=true):** Also OpenAI (`openai_model_fast` / `openai_model_smart`).

Groq is not used. If you still have `GROQ_API_KEY` or `GROQ_MODEL` in `.env`, they are ignored. You must set `OPENAI_API_KEY` and optionally `OPENAI_MODEL`.

---

## WebRTC connection (“Call” does not connect)

The Pipecat dev server uses **uvicorn** + **SmallWebRTC**. Typical failures:

1. **Windows + `localhost`:** The browser may resolve `localhost` to **IPv6** (`::1`) while the server is only listening on **IPv4**. **Fix:** open **`http://127.0.0.1:7860/client`** (not `localhost`). The app defaults **`HOST=127.0.0.1`** in `agent/config.py` and passes `--host` into the Pipecat runner from `agent/bot.py` / `agent/main.py`.
2. **Wrong URL:** Use **`/client`** — e.g. `http://127.0.0.1:7860/client`. Root `/` redirects to `/client/`.
3. **Port / firewall:** Another process may be using `7860` (change `PORT` in `.env`). Corporate VPN or firewall can block **UDP** used by WebRTC — try disconnecting VPN or allow Python through Windows Firewall.
4. **Server not running:** You should see `Uvicorn running on http://...` in the terminal. If startup errors mention missing packages, reinstall: `uv sync` (needs `pipecat-ai[webrtc,runner]`).
5. **Docker / LAN:** Set **`HOST=0.0.0.0`** in `.env` or compose so the server accepts non-loopback connections; then open `http://<your-LAN-IP>:7860/client` from another device.
6. **Port already in use (Windows `10048`, or “connects but Call fails”):** A **stale** `python -m agent.bot` may still hold `7860`. Pipecat can print “Bot ready!” even when uvicorn **failed to bind**; your browser then talks to the **wrong** process. **Fix:** stop old Python processes, or set `PORT=7861` in `.env`. The app now **exits early** if the TCP port is already taken (after argv defaults). Check: `netstat -ano | findstr :7860` then `taskkill /PID <pid> /F`.

---

## Pipeline flow (where it can break)

```
User speaks → [STT Deepgram] → [User aggregator + VAD] → [Barge-in logger] → [Context trim]
    → (optional IntentRouter) → [LLM OpenAI] → [FunctionCallFilter] → [TTS Cartesia] → [Output]
                                                                           ↑
Tool call: LLM emits tool → handler runs → result_callback(result) → context gets result
         → LLM invoked again → should emit spoken reply → TTS → output
```

**Break points (why you get silence or “breaking”):**

1. **On client connect:** `bot.py` sets `metrics_ref["metrics"].set_model_used(OPENAI_MODEL)`. If that line referenced an undefined name (e.g. `GROQ_MODEL`), the handler would crash and the pipeline could stop — **fixed** to use `OPENAI_MODEL`.
2. **STT:** Deepgram fails or returns nothing → no user message → no LLM turn.
3. **LLM:** OpenAI timeout, rate limit, or error → no response frames → silence.
4. **Tool call:** Handler throws or times out → `safe_tool_call` calls `result_callback` with an error message. If the **follow-up LLM call** (with that result in context) fails or never runs, you get silence after “Let me check that for you.”
5. **TTS:** Cartesia error or empty text → nothing to play.
6. **Context:** Trimmer or context state corrupt → LLM gets bad context and may not reply.

So “it worked then broke” is often: **first turn works (no tool), second turn does a tool and the follow-up LLM turn or tool result delivery fails.**

---

## How to see where latency and breakage happen

1. **Logs:** Run the bot and watch for:
   - `[LATENCY] User→Bot: X.XXs` — total time from user stop speaking to bot speech.
   - `[LATENCY] Breakdown:` — per-stage times (STT, LLM TTFB, TTS, etc.).
   - `Tool 'check_availability' timed out` or `Tool '...' failed` in `agent/core/errors.py` → tool or DB issue.
   - Any Python traceback → crash in that handler (e.g. on_client_connected, tool, or pipeline stage).

2. **Metrics file:** After a call, `data/metrics.jsonl` has per-call `turns` with `total_response_ms` and, if available, `llm_ttfb_ms`, `stt_time_ms`, `tts_ttfb_ms`. Use this to see which stage is >500ms.

3. **Consistent 500ms or below:**  
   - **LLM TTFB** is usually the biggest (OpenAI first token). Use a fast model (`gpt-4o-mini`), keep `max_completion_tokens` modest (e.g. 150–200), and avoid huge context.  
   - **STT:** Lower `DEEPGRAM_UTTERANCE_END_MS` / `DEEPGRAM_ENDPOINTING` for faster turn-taking but more cut-offs.  
   - **TTS:** `TTS_LOW_LATENCY=true` uses TOKEN mode (first audio sooner, less natural); `false` uses SENTENCE (more natural, higher latency).  
   - **Tools:** Tool timeout is 12s; if the tool is slow (e.g. DB), fix the DB or reduce work so the tool returns well under 500ms when you want to stay under budget.

---

## Recommended config for ≤500ms and natural voice

- **Strict ≤500ms, natural pacing:**  
  `OPENAI_MODEL=gpt-4o-mini`  
  `DEEPGRAM_UTTERANCE_END_MS=400`  
  `DEEPGRAM_ENDPOINTING=200`  
  `TTS_LOW_LATENCY=false` (SENTENCE mode for natural pacing; if latency goes above 500ms, try `true`).  
  `LLM_MAX_TOKENS=200` (or 150 to trim a bit more).

- **Aggressive &lt;500ms, accept more cut-offs:**  
  `DEEPGRAM_UTTERANCE_END_MS=300`  
  `DEEPGRAM_ENDPOINTING=150`  
  `TTS_LOW_LATENCY=true`  
  Keep `OPENAI_MODEL=gpt-4o-mini`.

- **Dual-LLM:** Set `ENABLE_DUAL_LLM=false` until the single-LLM path is stable and under 500ms; then re-enable if you want simple vs complex routing.

**Learning from every call:** Outcomes are written to `data/feedback.jsonl`; the next call's system prompt gets a short "LEARN FROM RECENT CALLS" block (see `agent/learning.py`). Config: `ENABLE_LEARN_FROM_FEEDBACK=true`, `FEEDBACK_MAX_ENTRIES=50`, `FEEDBACK_MAX_CHARS=600`.

---

## Checklist when the pipeline “breaks”

- [ ] `.env` has `OPENAI_API_KEY` set (no need for Groq).
- [ ] No `NameError` or traceback in logs (e.g. from `GROQ_MODEL` or missing import).
- [ ] After “Let me check that for you,” check logs for tool timeout or tool error, then for a second LLM call.
- [ ] Inspect `[LATENCY] Breakdown` and `data/metrics.jsonl` to see which stage is slow or missing.

---

**See also:** [ARCHITECTURE.md](ARCHITECTURE.md) for the full pipeline picture; [docs/TOOLS.md](docs/TOOLS.md) for tool behavior.

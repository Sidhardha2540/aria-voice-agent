# MCP for tools & Mem0 for memory — assessment

## 1. MCP (Model Context Protocol) for tool calling

### What it is
- **MCP** is an open standard for AI agents to talk to external tools and data.
- **Pipecat** supports it: `MCPClient` discovers tools from an MCP server and registers them with the LLM (`pip install "pipecat-ai[mcp]"`).
- You run an **MCP server** (e.g. [pipecat-mcp-server](https://github.com/pipecat-ai/pipecat-mcp-server)) that exposes your tools; Pipecat connects via **stdio** or **SSE** and gets tool schemas + runs tools.

### Current setup (no MCP)
- Tools are **Python handlers** in this repo: `agent/tools/handlers.py` + `agent/tools/registry.py`.
- Pipecat’s LLM gets a `FunctionSchema` per tool and `register_function(name, handler)`.
- One process, no extra network hop, minimal latency.

### If we switched to MCP
- **Pros:** Standard protocol; tools could be shared across agents/clients; tool logic lives in a separate MCP server (e.g. different language or team).
- **Cons:** Extra process (or remote server) and serialization; **more latency** (round-trip to MCP server per tool call); more moving parts to run and debug. There is also a [known Pipecat issue](https://github.com/pipecat-ai/pipecat/issues/3950) with SSE creating a new session per tool call.
- **For a strict ≤500ms voice agent:** MCP adds latency (stdio/SSE + tool execution on the server). Keeping **in-process Python handlers** is better for latency and simplicity unless you have a strong need for shared/remote tools.

**Recommendation:** Stay with **in-process tools** for this voice agent. Consider MCP only if you need the same tools from multiple apps or from a non-Python stack.

---

## 2. Mem0 (Memo) for agent memory

### What it is
- **Mem0** is a memory platform: store and retrieve **semantic** memories (by meaning, not just key lookups).
- **Pipecat** has a first-class integration: `Mem0MemoryService` (`pip install "pipecat-ai[mem0]"`).
- You put the memory service **between the context aggregator and the LLM**. It:
  - **Retrieves** relevant memories for the current turn (search by user message) and injects them into context.
  - **Stores** conversation automatically (or you can use tools to add/update memories).

### Current setup (no Mem0)
- **Caller memory** is in **SQLite** (and/or Postgres): `callers` table keyed by **phone number**.
- Tools: `lookup_caller(phone_number)`, `save_caller(phone_number, name)`, and preferences (e.g. last doctor).
- Works well for: “Have you called before?” and “Returning caller: Jane, last visited …”. No semantic search; only exact phone lookup.

### If we added Mem0
- **Pros:**
  - **Semantic memory:** e.g. “I prefer morning slots” or “I have a skin condition” can be recalled even if the user says it differently later.
  - **Cross-session:** Mem0 is built for long-term, user-scoped memory.
  - **Pipecat-native:** `Mem0MemoryService` in the pipeline; no need to expose memory as tools only (you can still keep `lookup_caller` for phone-based lookup).
- **Cons:**
  - **Extra latency:** Before each LLM turn, Mem0 search runs (API call). For ≤500ms you’d need to keep this fast (e.g. small `search_limit`, low `search_threshold` or async inject).
  - **Two memory systems:** Caller DB (phone, appointments, preferences) vs Mem0 (semantic past convos). You’d need a clear split: e.g. **structured data (appointments, caller id) → DB**; **unstructured “remember what they said” → Mem0**.
  - **Cost and dependency:** Mem0 API key and usage; one more service to rely on.

**Recommendation:** Adding **Mem0** can make the agent feel “smarter” (remembers what was said, not just who called). To keep latency good:
- Use Mem0 for **retrieval only** in the pipeline (inject N most relevant memories).
- Keep **caller DB** for: phone lookup, appointment history, and preferences (e.g. last_doctor).
- Optionally add Mem0 **tools** (e.g. `search_memories`, `save_memory`) so the LLM can explicitly read/write semantic facts; then tune `search_limit` and thresholds.

---

## 3. Summary

| | MCP for tools | Mem0 for memory |
|---|----------------|------------------|
| **Use it?** | **No** for this voice agent (latency, complexity). | **Optional yes** for better “remember what they said” and more natural follow-ups. |
| **Latency** | Adds round-trip to MCP server. | Adds Mem0 search before LLM; tune limits/thresholds. |
| **Current** | In-process Python tools. | SQLite/Postgres caller DB by phone. |
| **When to add** | When you need shared/remote tools across apps. | When you want semantic, cross-session memory on top of caller DB. |

**Practical path:**  
- Keep **tools as they are** (no MCP).  
- If you want better agent memory: add **Pipecat Mem0MemoryService** in the pipeline (with `user_id` e.g. from phone or session), keep caller DB for structured data, and optionally expose Mem0 as tools. Measure latency (Mem0 search + LLM) and keep under your 500ms budget.

Backboard.io Integration Plan — Full Detail                                                                                         
                                                                                                                                   
 Context

 Replacing OpenRouter with Backboard.io as the LLM provider for the DeltaHacks12 hackathon (Backboard.io Founder's Choice category,
 $500 prize). Backboard provides a unified API with persistent memory/RAG via its thread system. The integration touches the core
 LLM client, CLI, agents, webapp, and documentation.

 ---
 Backboard API Reference

 Base URL: https://app.backboard.io/api

 Authentication: X-API-Key: {BACKBOARD_API_KEY} header on all requests.

 Workflow:
 1. Create an assistant: POST /assistants (JSON body with llm_provider, llm_model_name, tools)
 2. Create a thread: POST /assistants/{assistant_id}/threads (empty JSON body)
 3. Send messages: POST /threads/{thread_id}/messages (form data, not JSON)

 Message parameters (form-encoded):
 ┌──────────────┬────────────────────┬─────────────────────────────────────────────────────────────┐
 │  Parameter   │       Values       │                           Purpose                           │
 ├──────────────┼────────────────────┼─────────────────────────────────────────────────────────────┤
 │ content      │ string             │ The message text                                            │
 ├──────────────┼────────────────────┼─────────────────────────────────────────────────────────────┤
 │ stream       │ "true" / "false"   │ Enable SSE streaming                                        │
 ├──────────────┼────────────────────┼─────────────────────────────────────────────────────────────┤
 │ memory       │ "auto" / "off"     │ Enable Backboard persistent memory                          │
 ├──────────────┼────────────────────┼─────────────────────────────────────────────────────────────┤
 │ send_to_llm  │ "true" / "false"   │ Whether to get an LLM response (false = store context only) │
 ├──────────────┼────────────────────┼─────────────────────────────────────────────────────────────┤
 │ llm_provider │ e.g. "openai"      │ Model provider                                              │
 ├──────────────┼────────────────────┼─────────────────────────────────────────────────────────────┤
 │ model_name   │ e.g. "gpt-4o-mini" │ Specific model                                              │
 └──────────────┴────────────────────┴─────────────────────────────────────────────────────────────┘
 Non-streaming response: {"content": "...", "memory_operation_id": "...", "retrieved_memories": [...]}

 Streaming SSE events:
 - {"type": "content_streaming", "content": "chunk text"} — text delta
 - {"type": "memory_retrieved", "memories": [...]} — memory context (informational)
 - {"type": "run_ended", "memory_operation_id": "...", "retrieved_memories": [...]} — done

 Key differences from OpenRouter:
 - No native response_format: {type: "json_object"} — must instruct JSON via prompt
 - No native function calling / tool_calls format — agents already parse tools from text
 - Messages are form-encoded, not JSON body
 - Requires assistant + thread creation before messaging (2 extra HTTP calls)

 ---
 File 1: src/docbot/llm.py — Complete Rewrite

 This is the core integration. Every other file either works automatically through the preserved chat()/ask() interface or needs
 only minor text changes.

 Constants

 # OLD
 OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
 DEFAULT_MODEL = "openai/gpt-oss-20b"

 # NEW
 BACKBOARD_BASE_URL = "https://app.backboard.io/api"
 DEFAULT_MODEL = "openai/gpt-4o-mini"

 New Helper: _split_model

 def _split_model(model: str) -> tuple[str, str]:
     """Split 'provider/model_name' → (llm_provider, model_name)."""
     if "/" in model:
         provider, name = model.split("/", 1)
         return provider, name
     return "openai", model

 StreamDelta — Simplified

 Remove tool_index, tool_name, tool_args_chunk fields (Backboard has no native tool call streaming). Keep only:
 @dataclass
 class StreamDelta:
     content: str | None = None
     finish_reason: str | None = None

 Remove StreamedToolCall class entirely

 No longer needed — Backboard doesn't emit tool call deltas.

 LLMClient Dataclass — New Fields

 @dataclass
 class LLMClient:
     api_key: str
     model: str = DEFAULT_MODEL
     max_tokens: int = 8192
     temperature: float = 0.3
     backoff_enabled: bool = True
     max_retries: int = 4
     base_backoff_seconds: float = 0.05
     adaptive_reduction_factor: float = 0.6
     max_concurrency: int = 6
     # Existing internal fields preserved:
     _sem: asyncio.Semaphore
     _failure_streak: int
     _stats_lock: asyncio.Lock
     _total_calls: int
     _retry_count: int
     # NEW Backboard-specific:
     _assistant_id: str | None = field(default=None, init=False, repr=False)
     _init_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

 Note: _init_lock is a threading.Lock (not asyncio.Lock) because _ensure_assistant_sync is called from threads via
 asyncio.to_thread.

 __post_init__ — Unchanged

 def __post_init__(self) -> None:
     self._sem = asyncio.Semaphore(max(1, self.max_concurrency))
     self._stats_lock = asyncio.Lock()

 New: _json_headers() and _form_headers()

 def _json_headers(self) -> dict[str, str]:
     return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

 def _form_headers(self) -> dict[str, str]:
     return {"X-API-Key": self.api_key}

 New: _ensure_assistant_sync()

 Lazily creates a Backboard assistant on first use. Thread-safe via threading.Lock.

 def _ensure_assistant_sync(self) -> str:
     with self._init_lock:
         if self._assistant_id:
             return self._assistant_id
         provider, model_name = _split_model(self.model)
         body = json.dumps({
             "name": "docbot",
             "description": "Documentation generator assistant",
             "llm_provider": provider,
             "llm_model_name": model_name,
             "tools": [],
         }).encode("utf-8")
         req = urllib.request.Request(
             f"{BACKBOARD_BASE_URL}/assistants",
             data=body,
             headers=self._json_headers(),
             method="POST",
         )
         try:
             with urllib.request.urlopen(req, timeout=30) as resp:
                 data = json.loads(resp.read().decode("utf-8"))
         except urllib.error.HTTPError as exc:
             error_body = exc.read().decode("utf-8", errors="replace")
             raise RuntimeError(f"Backboard assistant creation failed ({exc.code}): {error_body}") from exc
         self._assistant_id = data["assistant_id"]
         return self._assistant_id

 New: _create_thread_sync()

 def _create_thread_sync(self) -> str:
     assistant_id = self._ensure_assistant_sync()
     req = urllib.request.Request(
         f"{BACKBOARD_BASE_URL}/assistants/{assistant_id}/threads",
         data=b"{}",
         headers=self._json_headers(),
         method="POST",
     )
     try:
         with urllib.request.urlopen(req, timeout=30) as resp:
             data = json.loads(resp.read().decode("utf-8"))
     except urllib.error.HTTPError as exc:
         error_body = exc.read().decode("utf-8", errors="replace")
         raise RuntimeError(f"Backboard thread creation failed ({exc.code}): {error_body}") from exc
     return data["thread_id"]

 New: _send_message_sync()

 Core method for sending a message to a Backboard thread. Uses form-encoded data.

 def _send_message_sync(
     self,
     thread_id: str,
     content: str,
     *,
     memory: str = "off",
     send_to_llm: bool = True,
 ) -> str:
     provider, model_name = _split_model(self.model)
     form_data = urllib.parse.urlencode({
         "content": content,
         "stream": "false",
         "memory": memory,
         "send_to_llm": str(send_to_llm).lower(),
         "llm_provider": provider,
         "model_name": model_name,
     }).encode("utf-8")
     req = urllib.request.Request(
         f"{BACKBOARD_BASE_URL}/threads/{thread_id}/messages",
         data=form_data,
         headers=self._form_headers(),
         method="POST",
     )
     try:
         with urllib.request.urlopen(req, timeout=120) as resp:
             data = json.loads(resp.read().decode("utf-8"))
     except urllib.error.HTTPError as exc:
         error_body = exc.read().decode("utf-8", errors="replace")
         raise RuntimeError(f"Backboard API error ({exc.code}): {error_body}") from exc
     return data.get("content", "")

 New: _flatten_messages()

 Converts OpenAI-format messages list into a single string for Backboard.

 @staticmethod
 def _flatten_messages(messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
     parts: list[str] = []
     for msg in messages:
         role = msg.get("role", "user")
         text = msg.get("content", "")
         if role == "system":
             parts.append(f"[System Instructions]\n{text}")
         elif role == "assistant":
             parts.append(f"[Previous Response]\n{text}")
         else:
             parts.append(text)
     if json_mode:
         parts.append("\nIMPORTANT: Respond with valid JSON only. No markdown fences, no explanation.")
     return "\n\n".join(parts)

 Rewrite: _call_sync()

 Creates ephemeral thread, flattens messages, sends. Replaces the OpenRouter HTTP call.

 def _call_sync(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
     thread_id = self._create_thread_sync()
     content = self._flatten_messages(messages, json_mode=json_mode)
     return self._send_message_sync(thread_id, content, memory="off")

 chat() — Unchanged

 Already calls _call_sync via asyncio.to_thread with retry/backoff. No changes needed.

 ask() — Unchanged

 Already builds messages list and calls chat(). No changes needed.

 New: ask_sync()

 Synchronous version for use in threads (fixes the LLM extractor event loop issue).

 def ask_sync(self, prompt: str, *, system: str | None = None, json_mode: bool = False) -> str:
     messages: list[dict[str, str]] = []
     if system:
         messages.append({"role": "system", "content": system})
     messages.append({"role": "user", "content": prompt})
     return self._call_sync(messages, json_mode=json_mode)

 New: create_thread()

 Public async method for agents/webapp to create threads.

 async def create_thread(self) -> str:
     return await asyncio.to_thread(self._create_thread_sync)

 New: send_thread_message()

 Public async method to send to existing thread with retry/backoff.

 async def send_thread_message(
     self,
     thread_id: str,
     content: str,
     *,
     memory: str = "auto",
     send_to_llm: bool = True,
 ) -> str:
     async with self._sem:
         attempt = 0
         while True:
             try:
                 result = await asyncio.to_thread(
                     self._send_message_sync, thread_id, content,
                     memory=memory, send_to_llm=send_to_llm,
                 )
                 async with self._stats_lock:
                     self._total_calls += 1
                     self._failure_streak = max(0, self._failure_streak - 1)
                 return result
             except Exception as exc:
                 if not self.backoff_enabled or not _is_retryable(exc) or attempt >= self.max_retries:
                     raise
                 async with self._stats_lock:
                     self._retry_count += 1
                     self._failure_streak += 1
                     streak = self._failure_streak
                 penalty = (1.0 / max(0.1, self.adaptive_reduction_factor)) ** min(streak, 3)
                 wait_s = ((self.base_backoff_seconds * (2 ** attempt)) * penalty) + random.uniform(0, 0.01)
                 await asyncio.sleep(wait_s)
                 attempt += 1

 Rewrite: _stream_sync()

 Parse Backboard's SSE format instead of OpenRouter's.

 def _stream_sync(self, messages: list[dict], *, tools: list[dict] | None = None) -> Iterator[StreamDelta]:
     thread_id = self._create_thread_sync()
     content = self._flatten_messages(messages)
     provider, model_name = _split_model(self.model)
     form_data = urllib.parse.urlencode({
         "content": content,
         "stream": "true",
         "memory": "off",
         "send_to_llm": "true",
         "llm_provider": provider,
         "model_name": model_name,
     }).encode("utf-8")
     req = urllib.request.Request(
         f"{BACKBOARD_BASE_URL}/threads/{thread_id}/messages",
         data=form_data,
         headers=self._form_headers(),
         method="POST",
     )
     try:
         resp = urllib.request.urlopen(req, timeout=180)
     except urllib.error.HTTPError as exc:
         error_body = exc.read().decode("utf-8", errors="replace")
         raise RuntimeError(f"Backboard stream error ({exc.code}): {error_body}") from exc
     try:
         for raw_line in resp:
             line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
             if not line.startswith("data: "):
                 continue
             data_str = line[6:]
             if data_str.strip() == "[DONE]":
                 return
             try:
                 chunk = json.loads(data_str)
             except json.JSONDecodeError:
                 continue
             event_type = chunk.get("type", "")
             if event_type == "content_streaming":
                 text = chunk.get("content")
                 if text:
                     yield StreamDelta(content=text)
             elif event_type == "run_ended":
                 yield StreamDelta(finish_reason="stop")
                 return
     finally:
         resp.close()

 stream_chat() — Simplified

 Remove tool call accumulation logic (no more StreamedToolCall). Just yield content deltas. The tools parameter is accepted but
 ignored (tool instructions are in the prompt text).

 async def stream_chat(self, messages: list[dict], *, tools: list[dict] | None = None) -> AsyncIterator[StreamDelta]:
     async with self._sem:
         queue: asyncio.Queue[StreamDelta | None] = asyncio.Queue()
         def _run() -> None:
             try:
                 for delta in self._stream_sync(messages, tools=tools):
                     queue.put_nowait(delta)
             except Exception as exc:
                 queue.put_nowait(StreamDelta(finish_reason=f"__error__:{exc}"))
             finally:
                 queue.put_nowait(None)
         loop = asyncio.get_running_loop()
         fut = loop.run_in_executor(None, _run)
         error_msg: str | None = None
         try:
             while True:
                 delta = await queue.get()
                 if delta is None:
                     break
                 if delta.finish_reason and delta.finish_reason.startswith("__error__:"):
                     error_msg = delta.finish_reason[10:]
                     break
                 yield delta
         finally:
             await fut
         if error_msg:
             raise RuntimeError(error_msg)
         async with self._stats_lock:
             self._total_calls += 1
             self._failure_streak = max(0, self._failure_streak - 1)

 get_stats() — Unchanged

 _is_retryable() — Unchanged

 New import needed: import threading, import urllib.parse

 ---
 File 2: src/docbot/cli.py — Env Var + Messages

 Line 98: Environment variable

 # OLD
 api_key = os.environ.get("OPENROUTER_KEY", "").strip()
 # NEW
 api_key = os.environ.get("BACKBOARD_API_KEY", "").strip()

 Lines 103-106: Warning messages

 # OLD
 "[yellow]OPENROUTER_KEY not set. Running in template-only mode.[/yellow]"
 "[dim]Set OPENROUTER_KEY or pass --no-llm to suppress this warning.[/dim]"
 # NEW
 "[yellow]BACKBOARD_API_KEY not set. Running in template-only mode.[/yellow]"
 "[dim]Set BACKBOARD_API_KEY or pass --no-llm to suppress this warning.[/dim]"

 Line 344: LLM log message in generate

 # OLD
 console.print(f"[bold]LLM:[/bold] {effective_cfg.model} via OpenRouter")
 # NEW
 console.print(f"[bold]LLM:[/bold] {effective_cfg.model} via Backboard")

 Lines 274, 375, 471, 772: --model help text (4 occurrences)

 # OLD
 help="OpenRouter model ID."
 # NEW
 help="Model ID (provider/model)."

 ---
 File 3: src/docbot/extractors/llm_extractor.py — Fix Event Loop Issue

 Replace lines ~79-100 (the ThreadPoolExecutor/asyncio.run workaround)

 Current code (problematic):
 try:
     try:
         loop = asyncio.get_running_loop()
     except RuntimeError:
         loop = None
     if loop and loop.is_running():
         import concurrent.futures
         with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
             raw = pool.submit(asyncio.run, self._client.ask(prompt, system=_EXTRACT_SYSTEM)).result(timeout=60)
     else:
         raw = asyncio.run(self._client.ask(prompt, system=_EXTRACT_SYSTEM))

 New code (clean):
 try:
     raw = self._client.ask_sync(prompt, system=_EXTRACT_SYSTEM)

 This eliminates the event loop boundary problem entirely since ask_sync() is pure synchronous (no asyncio).

 ---
 File 4: src/docbot/agents/loop.py — Streaming Tool Call Fallback

 In run_agent_loop_streaming(): Add text-based tool parsing fallback

 After the streaming loop accumulates full_text, if no tool calls were detected via StreamedToolCall deltas (which Backboard will
 never emit), fall back to parse_tool_calls(full_text).

 The exact change: after the streaming accumulation loop ends and before checking if tool_calls:, add:
 # Backboard has no native tool call streaming — parse from text
 if not tool_calls and full_text:
     text_calls = parse_tool_calls(full_text)
     for tc in text_calls:
         tool_calls.append(tc)

 Also remove the StreamedToolCall import since it no longer exists:
 # OLD
 from ..llm import LLMClient, StreamedToolCall
 # NEW
 from ..llm import LLMClient

 Note: run_agent_loop() (non-streaming) already uses text-based parsing exclusively and needs no changes.

 ---
 File 5: src/docbot/web/server.py — Error Messages

 Line 1763:

 # OLD
 raise HTTPException(status_code=503, detail="LLM not configured (missing OPENROUTER_KEY).")
 # NEW
 raise HTTPException(status_code=503, detail="LLM not configured (missing BACKBOARD_API_KEY).")

 Line 2278: Same change.

 Line 116 (Dashboard.tsx service description — referenced inline):

 This is actually in webapp/src/components/Dashboard.tsx, handled in File 8.

 ---
 File 6: src/docbot/pipeline/orchestrator.py — Log Messages

 Line 336:

 # OLD
 console.print(f"[bold]LLM:[/bold] {llm_client.model} via OpenRouter (used at every step)")
 # NEW
 console.print(f"[bold]LLM:[/bold] {llm_client.model} via Backboard (used at every step)")

 Line 453: Same change.

 ---
 File 7: src/docbot/models.py — Docstring

 Line ~200 (model field description):

 # OLD
 """OpenRouter model ID for LLM calls."""
 # NEW
 """Model ID (provider/model_name) for Backboard API calls."""

 ---
 File 8: Documentation + Config Files

 .env.example

 # OLD
 OPENROUTER_KEY=sk-or-...
 # NEW
 BACKBOARD_API_KEY=...

 CLAUDE.md — Multiple updates:

 - Line 11: requires OPENROUTER_KEY → requires BACKBOARD_API_KEY
 - Line 29: .env file with OPENROUTER_KEY=sk-or-... → .env file with BACKBOARD_API_KEY=...
 - Line 72: minimal async wrapper around OpenRouter → minimal async wrapper around Backboard.io

 README.md

 - Line 33: OPENROUTER_KEY → BACKBOARD_API_KEY
 - Line 69: OpenRouter model ID → Model ID

 webapp/src/components/Dashboard.tsx

 - Line 116: Update OpenRouter service description to reference Backboard
 - Line 326: OPENROUTER_KEY → BACKBOARD_API_KEY

 ROADMAP.md

 - Line 25: OpenRouter only for LLM provider → Backboard.io for LLM provider

 ---
 Files NOT Modified (work automatically)

 These all use llm_client.ask() or llm_client.chat() which are preserved:

 - src/docbot/pipeline/planner.py — llm_client.ask(prompt, system=_PLANNER_SYSTEM)
 - src/docbot/pipeline/explorer.py — llm_client.ask(prompt, system=_EXPLORER_SYSTEM)
 - src/docbot/pipeline/reducer.py — llm_client.ask() × 2 (analysis + mermaid)
 - src/docbot/pipeline/renderer.py — llm_client.ask() × 3 (scope docs + README + arch)
 - src/docbot/agents/scope_agent.py — calls run_agent_loop()
 - src/docbot/agents/file_agent.py — calls run_agent_loop()
 - src/docbot/agents/symbol_agent.py — llm_client.ask()

 ---
 Key Design Decisions

 1. Ephemeral threads for stateless calls — each chat()/ask() creates a new thread with memory=off. Adds one extra HTTP roundtrip
 but preserves exact backward compatibility with zero behavior change.
 2. Message flattening — multi-message [{role, content}] arrays combined into single string with [System Instructions], [User],
 [Previous Response] markers. This is a standard technique for adapting chat-format messages to non-chat APIs.
 3. JSON mode via prompt — since Backboard has no native response_format, append "Respond with valid JSON only" when json_mode=True.
  All existing callers already include similar instructions in their prompts, so this is reinforcement.
 4. ask_sync() for extractors — cleanly eliminates the ThreadPoolExecutor/asyncio.run workaround that caused "semaphore bound to
 different event loop" errors.
 5. StreamedToolCall removed — Backboard has no native function calling in its streaming format. The agent system already parses
 tool calls from text (3-tier fallback: JSON, code blocks, inline regex), so nothing is lost.
 6. Threading.Lock for assistant init — _ensure_assistant_sync runs in threads (via asyncio.to_thread), so it needs a threading.Lock
  not asyncio.Lock.

 ---
 Risks and Mitigations
 Risk: Form data encoding issues
 Impact: 400 errors from Backboard
 Mitigation: Use urllib.parse.urlencode(), test with simple call first
 ────────────────────────────────────────
 Risk: Extra latency from thread creation
 Impact: ~200ms per pipeline call
 Mitigation: Accept for now; could pool threads later
 ────────────────────────────────────────
 Risk: Message flattening quality
 Impact: LLM may misinterpret roles
 Mitigation: Clear role markers; test with representative prompts
 ────────────────────────────────────────
 Risk: No native JSON mode
 Impact: LLM may return non-JSON
 Mitigation: Existing callers already handle JSON parsing with fallback
 ────────────────────────────────────────
 Risk: Stale assistant ID
 Impact: 404 on thread creation
 Mitigation: Catch 404, reset _assistant_id, retry once
 ────────────────────────────────────────
 Risk: Streaming tool call gap
 Impact: Agents slower in streaming mode
 Mitigation: Text-based fallback parses after stream ends
 ---
 Verification Plan

 1. Pipeline: docbot generate ../DeltaHacks12 — all stages complete, docs generated
 2. Webapp: docbot serve ../DeltaHacks12 — chat, explore graph, graph routing, tours, service details all respond
 3. Agents: docbot generate --agents ../DeltaHacks12 — agent exploration completes
 4. Template mode: docbot generate --no-llm ../DeltaHacks12 — no Backboard calls made
 5. Ctrl+C: interrupt during generate — clean exit
 6. Missing key: unset BACKBOARD_API_KEY, run generate — graceful fallback message

 ---
 Implementation Order

 1. src/docbot/llm.py — core rewrite (everything depends on this)
 2. src/docbot/extractors/llm_extractor.py — fix event loop issue
 3. src/docbot/agents/loop.py — streaming fallback
 4. src/docbot/cli.py — env var + messages
 5. src/docbot/web/server.py — error messages
 6. src/docbot/pipeline/orchestrator.py — log messages
 7. src/docbot/models.py — docstring
 8. .env.example, CLAUDE.md, README.md, ROADMAP.md, Dashboard.tsx — docs
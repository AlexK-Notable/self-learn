# Empirical SDK probes for the pane design — 2026-07-12

**Machine:** komi's Arch/CachyOS desktop (Linux 7.1.1-2-cachyos)
**Date:** 2026-07-12
**SDK:** `claude-agent-sdk` **0.2.116** (Python, via `uv run --with claude-agent-sdk`, Python 3.13 resolved by uv)
**CLI:** `claude` **2.1.207**
**Auth:** Claude Max subscription OAuth (`~/.claude/.credentials.json`); no API-key env vars set. All runs billed against the subscription and completed normally.
**Method:** every claim below is backed by an executed run. Scripts + raw outputs live in `/tmp/claude-1000/-home-komi-repos-claude-skills/f687d7ce-a89a-439a-abb5-b18d8e2f43c9/scratchpad/sdk-probes/` (`probe1_stream.py`, `probe1b_output.txt`, `probe2_canusetool.py`, `probe2b_client.py`, `probe3_settings.py`, `probe*_output*.txt`). Scratchpad is session-scoped — outputs are reproduced inline here because the directory is ephemeral.

---

## Probe 1 — partial-message streaming granularity: **VERIFIED (chunk-level, ~0.2 s cadence — good enough for live rendering)**

### Code (condensed)

```python
opts = ClaudeAgentOptions(model="claude-haiku-4-5-20251001", max_turns=1,
                          allowed_tools=[], include_partial_messages=True, setting_sources=[])
async for msg in query(prompt="Write a 150-word paragraph about rivers.", options=opts):
    if isinstance(msg, StreamEvent): ...  # msg.event is a raw Anthropic stream event dict
```

### Observed

(a) **Yes — incremental deltas arrive before the final message.** `StreamEvent` messages with `content_block_delta` events streamed in starting at t=1.7 s; the complete `AssistantMessage` arrived at t=4.6 s, `ResultMessage` at t=4.6 s.

(b) **Event types observed** (counts from run 1): `message_start` ×1, `content_block_start` ×2, `content_block_delta` ×17, `content_block_stop` ×2, `message_delta` ×1, `message_stop` ×1 — the raw Anthropic Messages streaming event vocabulary, wrapped in a `StreamEvent` dataclass with `uuid`, `session_id`, `event`, `parent_tool_use_id`. Deltas come in two flavors: `thinking_delta` (block index 0) then `text_delta` (block index 1). Sample event verbatim (run 2, text delta):

```json
{"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Rivers are"}}
```

and the SDK wrapper (run 1, thinking delta):

```json
{"uuid": "51014351-563b-4703-ace9-5df0bceb8bb8",
 "session_id": "9db0147d-6465-4c6b-9efb-9bca2652a1f2",
 "parent_tool_use_id": null,
 "event": {"type": "content_block_delta", "index": 0,
           "delta": {"type": "thinking_delta", "thinking": "The user is asking", "estimated_tokens": null}}}
```

(c) **Delta counts for the ~150-word answer:** run 1: 17 total `content_block_delta` (5 thinking + 12 text) for a 148-word answer. Run 2: 11 `text_delta` events carrying 160 words → **~14.5 words (~75–170 chars) per delta**. Delta payload sizes observed: `[10, 119, 132, 116, 82, 100, 162, 141, 90, 75, 169]` chars.

(d) **Wall-time:** run 2 text deltas spanned first 2.389 s → last 4.457 s = **2.07 s**, with remarkably uniform inter-delta gaps of **~0.19–0.21 s** (`[0.188, 0.207, 0.209, 0.207, 0.206, 0.212, 0.214, 0.205, 0.214, 0.205]`).

### Verdict

**VERIFIED — granularity is chunk-level, not per-token**: the CLI coalesces the API's token stream into ~15-word flushes every ~200 ms. That is coarser than raw Anthropic SSE but comfortably smooth for live typing-style rendering (5 visual updates/second). Thinking deltas stream too and are distinguishable by `delta.type`.

**Consequence for the pane design pin:** partial streaming over the SDK is real and usable for a live pane; render on `text_delta` events keyed by `parent_tool_use_id`/block index, expect ~5 Hz chunk updates rather than per-token animation.

---

## Probe 2 — `can_use_tool` exact-file permission callback: **VERIFIED (pass condition met), with three sharp footguns**

### Code (condensed, final working version — `probe2b_client.py`)

```python
async def can_use_tool(tool_name, tool_input, context):
    if tool_name == "Edit":
        fp = tool_input.get("file_path", "")
        if fp.endswith("a.md"): return PermissionResultAllow()
        if fp.endswith("b.md"): return PermissionResultDeny(
            message="Policy: edits to b.md are forbidden by the pane permission gate. Do not retry via other tools.")
    return PermissionResultAllow()

opts = ClaudeAgentOptions(model="claude-haiku-4-5-20251001", max_turns=8, cwd=str(WORKDIR),
                          permission_mode="default", can_use_tool=can_use_tool, setting_sources=[])
async with ClaudeSDKClient(options=opts) as client:          # NOT query() — see footgun 3
    await client.query(f"Edit {WORKDIR}/a.md to replace X with Y. Then edit {WORKDIR}/b.md ...")
    async for msg in client.receive_response(): ...
```

### Observed

(a) **Callback invocations** (verbatim log lines from the passing run; paths abbreviated as `$W` = the p2work dir):

```
CALLBACK: tool=Edit input={"file_path": "$W/a.md", "old_string": "hello X", "new_string": "hello Y", "replace_all": false}
CALLBACK -> ALLOW a.md
CALLBACK: tool=Edit input={"file_path": "$W/b.md", "old_string": "hello X", "new_string": "hello Y", "replace_all": false}
CALLBACK -> DENY b.md
```

Note: the two `Read` calls that preceded the edits did **not** invoke the callback — reads are auto-approved in `default` permission mode and never reach `can_use_tool`.

(b) **Denial reason surfaced to the agent** as an error tool result, verbatim: `TOOL_RESULT (is_error=True): "Policy: edits to b.md are forbidden by the pane permission gate. Do not retry via other tools."` The agent reacted correctly — it did not retry, and its final text reported: "the second file (`b.md`) has a permission restriction in place … The system indicates 'edits to b.md are forbidden by the pane permission gate.'" The `ResultMessage` also carried a structured record: `permission_denials: [{"tool_name": "Edit", "tool_use_id": "toolu_011bx…", "tool_input": {"file_path": "…/b.md", …}}]`, `is_error=False`, cost $0.0255.

(c) **Final file contents — PASS:** `a.md: 'hello Y\n'`, `b.md: 'hello X\n'` (a.md changed, b.md untouched).

(d) **Footguns (all hit empirically before the passing run):**

1. **String prompt → hard error.** `query(prompt="...", can_use_tool=...)` raises `ValueError: can_use_tool callback requires streaming mode. Please provide prompt as an AsyncIterable instead of a string.`
2. **`allowed_tools` shadows the callback.** With `allowed_tools=["Read","Edit"]` the SDK itself warned: `CanUseToolShadowedWarning: can_use_tool will not be invoked for: Read, Edit. An allowed_tools entry that allows a whole tool auto-approves it before the callback is consulted. To gate every tool call, use a PreToolUse hook; or narrow the entry so calls fall through to can_use_tool. Allow rules from settings files can also shadow the callback but are not visible here.` The callback never fired in that run. Do NOT pre-allow the tool you want to gate.
3. **`query()` + finite AsyncIterable breaks the control channel.** Wrapping the prompt in a one-shot async generator made every gated tool call fail with `TOOL_RESULT (is_error=True): "Tool permission request failed: Error: Stream closed"` — the callback never executed, the agent burned 7 turns retrying (including `sed` via Bash, also denied), and the run died with `Reached maximum number of turns (6→raised)`. Silver lining: even in this broken state nothing was written — permission requests fail **closed**. The reliable pattern is `ClaudeSDKClient`, which keeps the bidirectional stream open.
4. **Path shape:** with the tools invoked normally, `tool_input.file_path` arrived as an **absolute** path even though nothing forced that; but in an earlier run the model guessed bare `/a.md` from a relative prompt. Match on absolute paths (or resolve before comparing), and give the agent absolute paths in the prompt.

### Verdict

**VERIFIED** — `can_use_tool` gives per-invocation, input-inspecting allow/deny with the deny reason surfaced verbatim to the model, and denial is recorded in `ResultMessage.permission_denials`. But it only works via `ClaudeSDKClient` (or a held-open stream), only for tools not already allowed elsewhere, and only for permission-requiring tools (reads bypass it).

**Consequence for the pane design pin:** the exact-file write-gate design is viable as specced, but the pane runtime must be built on `ClaudeSDKClient` with an empty/narrow `allowed_tools`, and the gate must canonicalize paths; a PreToolUse hook is the fallback if any allow-rule shadowing is in play.

---

## Probe 3 — `setting_sources` hygiene: **VERIFIED (empty = ~11× smaller cache write, zero hooks) — but the documented default is WRONG on this stack**

### Code (condensed)

```python
# one-turn "Say OK and nothing else." with include_hook_events=True, three variants:
#   A: setting_sources=["user","project","local"]   B: setting_sources unset   C: setting_sources=[]
opts = ClaudeAgentOptions(model="claude-haiku-4-5-20251001", max_turns=1, allowed_tools=[],
                          include_hook_events=True, setting_sources=VARIANT)
```

### Observed (single sequential run, A then B then C, from `probe3_output.txt`)

| Variant | cache_creation_input_tokens | cache_read_input_tokens | hooks fired (`hook_started`) | slash_commands | plugins | permissionMode | cost |
|---|---|---|---|---|---|---|---|
| A `["user","project","local"]` | **33,972** | 14,894 | **13** (6 SessionStart, 4 UserPromptSubmit, 3 Stop) | 139 | 13 | `dontAsk` (from user settings) | $0.0696 |
| B unset (SDK default) | 0 (prefix identical to A → read 48,866) | **48,866** | **13** (same set) | 139 | 13 | `dontAsk` | $0.0053 |
| C `[]` | **3,027** | 14,894 | **0** | 43 | **0** | `default` | $0.0083 |

Distinctive user-environment hook content observed in A and B (verbatim excerpts from `hook_response` events): the superpowers SessionStart injector — `"additionalContext": "<EXTREMELY_IMPORTANT>\nYou have superpowers.\n\n**Below is the full content of your 'superpowers:using-superpowers' sk…"` — plus a remember-plugin `=== HANDOFF ===` banner and a `━━━…━━━` ruled UserPromptSubmit banner (the skill-activation hook's frame). Variant C: zero `hook_started`/`hook_response` events, `plugins: []`, and only built-in + managed slash commands (43 vs 139).

**Pass condition met:** emptied sources → cache write 3,027 vs 33,972 tokens (**~11× smaller**; total startup prefix 17.9k vs 48.9k) and **no user hooks fired**.

**Bonus finding (decision-relevant):** on SDK 0.2.116 + CLI 2.1.207, **leaving `setting_sources` unset does NOT mean "no filesystem settings"** — variant B's init message was byte-identical to variant A's (same 139 commands, 13 plugins, `dontAsk` permission mode, all 13 hooks fired), and its `cache_creation=0 / cache_read=48,866` proves the prompt prefix was exactly A's. Whatever older SDK docs say about the default being "no settings," on this stack the default loads the user's full environment. Hygiene must be **explicit**: `setting_sources=[]`.

### Verdict

**VERIFIED** — `setting_sources=[]` delivers the clean-room startup (11× smaller cache write, zero user hooks, zero plugins); the SDK default is empirically equivalent to full user/project/local loading here and must not be relied on for isolation.

**Consequence for the pane design pin:** every pane-spawned SDK session must pass `setting_sources=[]` explicitly (plus its own curated options) — omitting it silently drags in the user's 30k+-token plugin/hook environment, `dontAsk` permission mode included, which would also neuter Probe 2's permission gate.

---

## Cross-probe notes

- Costs per probe run: $0.004–0.07 (haiku, subscription OAuth). Total spend for all probes: well under $0.30.
- `ResultMessage.usage` carries full API usage detail including `cache_creation.ephemeral_1h_input_tokens` and per-iteration breakdowns — sufficient for pane-side cost telemetry without extra instrumentation.
- `RateLimitEvent` messages appear mid-stream on the Max OAuth path (observed in every run); pane message loops must tolerate unknown message types.

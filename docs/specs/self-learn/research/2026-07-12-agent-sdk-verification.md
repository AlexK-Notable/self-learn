# Claude Agent SDK — live-doc capability verification (2026-07-12)

*Produced by an independent research agent against live documentation
(code.claude.com Agent SDK docs, platform.claude.com, the two official
GitHub repos) on 2026-07-12, for the G-3 TUI design. Every section cites
its sources. Shareable with blind reviewers (research/, not reviews/).*

*Orchestrator's flags — claims in this report that the 09 design treats as
**verify-at-build pins with fallbacks** rather than settled facts:*

1. *§3's "path-scoped allow rules not supported in `allowedTools`" sits in
   tension with Claude Code's documented permission-rule syntax
   (`Edit(path/**)` etc.) that 08 §7's worker pin relies on for the CLI.
   The 09 pane design therefore does **not** depend on path-scoped
   `allowedTools`: the guaranteed mechanism is the `canUseTool` callback +
   `disallowedTools: ["Bash"]` + `cwd` confinement; path-scoped allow
   rules are an optimization to verify at build.*
2. *§5's "partial/incomplete messages are not exposed" — token-level
   partial streaming (`includePartialMessages` or equivalent) is treated
   as unverified. The pane design must degrade gracefully to per-block
   rendering with an activity indicator.*
3. *§2's cross-process cache-hit behavior is explicitly flagged
   under-documented by the report itself (Risks #1). The design treats
   cache hits as opportunistic economics, never as a correctness or UX
   dependency.*

---

# Claude Agent SDK Capability Report

## 1. Session Creation & Lifecycle

**Package APIs:**
The TypeScript SDK provides `query()` and streaming-input mode for managing sessions. Python offers both `query()` (one-shot) and `ClaudeSDKClient` (multi-turn with internal session tracking).

**Session Creation:**
- **`query()` function** (both SDKs): Creates a single agent session that can span multiple agentic turns. Returns an async iterable of messages. ([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview.md))
- **`ClaudeSDKClient` (Python only)**: Stateful session wrapper that tracks session ID internally across multiple `client.query()` and `client.receive_response()` calls without manual ID passing. Acts as an async context manager. ([Sessions guide](https://code.claude.com/docs/en/agent-sdk/sessions.md))
- **TypeScript `continue: true`**: Automatic resume of the most recent session on disk without explicit ID capture. ([Sessions guide](https://code.claude.com/docs/en/agent-sdk/sessions.md))

**Interactive vs. Single-Shot:**
- **Interactive (Streaming Input Mode)**: Default for both SDKs. Agent runs as a long-lived process. Supports interruption, permission requests, image uploads, and multi-message queueing. ([Streaming vs. single mode](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode.md))
- **Single-Shot**: One `query()` call with one prompt. No image attachments or mid-session interruption.

**Session Resume and Forking:**
- **Resume by ID**: `resume` option loads a specific prior session and continues from its end state. Session ID is captured from the `ResultMessage.session_id` field.
- **Fork**: `fork_session: true` (Python) / `forkSession: true` (TypeScript). Creates a new session branching from an existing one's history; original remains unchanged. ([Sessions guide](https://code.claude.com/docs/en/agent-sdk/sessions.md))
- **Session Storage**: Sessions persist to `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` on disk, or `$CLAUDE_CONFIG_DIR/projects/...` if env var is set. Can be moved across machines if cwd matches. ([Sessions guide](https://code.claude.com/docs/en/agent-sdk/sessions.md))

**Cost & Latency Implications:**
Each SDK call spawns a **child Claude Code subprocess** (a native binary or Node.js process) to manage the agentic loop. For TypeScript, the binary is bundled as an optional dependency. For Python, it is bundled automatically. Creating fresh sessions in rapid succession (e.g., 3–4 within 20–30 min) means spawning multiple processes, each with subprocess startup overhead (~hundreds of ms). Session resumption via `resume` or `continue` reuses the prior session's conversation history on disk; this avoids re-reading context but still spawns a fresh process for each call.

**On Interrupt/Abort:**
A cancelled or interrupted `query()` call (via language-level cancellation or exception) stops the agentic loop. The session file written to disk contains messages up to the interruption point; resuming continues from there. The running Claude Code subprocess is terminated. ([Sessions guide](https://code.claude.com/docs/en/agent-sdk/sessions.md))

**Sources:**
- https://code.claude.com/docs/en/agent-sdk/overview.md
- https://code.claude.com/docs/en/agent-sdk/sessions.md
- https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode.md
- https://code.claude.com/docs/en/agent-sdk/quickstart.md

## 2. Prompt Caching

**Automatic Caching in Agent SDK:**
The Agent SDK does **not** automatically enable prompt caching on its own. Caching is a feature of the underlying Anthropic API and must be explicitly requested. The SDK reads `ENABLE_PROMPT_CACHING_1H` or `ENABLE_PROMPT_CACHING` environment variables inherited from the host process, which control whether the API request asks for caching. ([Claude Platform on AWS docs](https://code.claude.com/docs/en/claude-platform-on-aws.md) notes: "Prompt caching is enabled automatically" when using Claude Platform on AWS, meaning the routing layer enables it by default.)

**Across Separate Sessions:**
Two sequential fresh sessions with identical system prompts **do not automatically share cache** because each session spawns a new subprocess. The Claude Code CLI subprocess manages its own API connection; cache state is managed at the Anthropic API level, not in the SDK.

However, **with `excludeDynamicSections` option**, the system prompt is made byte-identical across different machines/directories: dynamic sections (cwd, git flag, OS version, shell, auto-memory paths) move into the first user message instead of the system prompt. This allows identical static system-prompt text to be cached across sessions if the API key is the same. ([Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md))

**Cache TTL and Invalidation:**
Cache TTL is controlled at the API level, not the SDK. The default is 5 minutes; setting `ENABLE_PROMPT_CACHING_1H=1` requests 1-hour TTL with higher billing. ([Claude Platform on AWS docs](https://code.claude.com/docs/en/claude-platform-on-aws.md))

**Documented Cache Control in SDK:**
- **`excludeDynamicSections` option** (v0.2.98 Python / v0.3.98 TypeScript or later): Removes per-session context from system prompt to maximize cross-session cache reuse. Only applies to preset form of `systemPrompt`. ([Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md))
- **Tool results cache**: When using Tool Runner's `generate_tool_call_response()`, you can manually add `cache_control: { type: "ephemeral" }` to tool result blocks to cache large returned data. ([Tool Runner docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner.md))

**Cache Scope and API Key:**
Cache is per-API-key at the Anthropic API level. Two sessions with the same API key and identical byte-stable system prompts will hit the cache. The SDK does not expose per-session cache control beyond `excludeDynamicSections`.

**Authentication Note:**
The Agent SDK supports **API key authentication only** (including workspace API keys for Claude Platform on AWS / Bedrock / Vertex AI). It does **NOT** support claude.ai subscription OAuth login (which can offer rate limits / higher quotas in Claude Code desktop). Anthropic explicitly disallows third-party developers from offering claude.ai login for SDKs. ([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview.md), [Quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart.md))

**Sources:**
- https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md
- https://code.claude.com/docs/en/claude-platform-on-aws.md
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner.md
- https://code.claude.com/docs/en/agent-sdk/overview.md
- https://code.claude.com/docs/en/agent-sdk/quickstart.md

## 3. Tool Permissioning

**Core Options and Syntax:**

| Option (Python) | Option (TypeScript) | Semantics |
|---|---|---|
| `allowed_tools=["Read", "Bash"]` | `allowedTools: ["Read", "Bash"]` | Pre-approve named tools for this session |
| `disallowed_tools=["Bash"]` | `disallowedTools: ["Bash"]` | Remove tool from Claude's context; Claude cannot see/attempt it |
| `disallowed_tools=["Bash(rm *)"]` | `disallowedTools: ["Bash(rm *)"]` | Scoped deny rule: block Bash calls matching pattern; other Bash calls still permitted per permission mode |
| `permission_mode` | `permissionMode` | Global mode: "default" (prompt on unmatched), "dontAsk" (deny unmatched), "acceptEdits" (auto-approve file ops), "plan" (read-only + prompt on edits), "auto" (model classifier), "bypassPermissions" (approve all except explicit deny/ask rules) |

**Path Scoping:**
- **Allowed tools with paths**: Not supported in `allowedTools` itself [ORCHESTRATOR FLAG 1 — treat as verify-at-build; see header]. Use `additionalDirectories` to expand the agent's filesystem scope; all tools operate within cwd + `additionalDirectories`.
- **Denied tools with paths**: Supported in `disallowedTools`. ([Permissions guide](https://code.claude.com/docs/en/agent-sdk/permissions.md))

**Permission Mode Values and Behavior:**

| Mode | Auto-Approval Behavior |
|---|---|
| `default` | None; unmatched tools → `canUseTool` callback |
| `dontAsk` | Deny anything not in `allowedTools` or allow rules; never call `canUseTool` |
| `acceptEdits` | File operations auto-approved; others → permission mode / `canUseTool` |
| `plan` | Read-only tools run; file edits never auto-approved, always → `canUseTool` |
| `auto` | Model classifier approves/denies each tool call |
| `bypassPermissions` | All tools auto-approved except explicit deny/ask rules; hooks still run |

**canUseTool Callback Signature (Python):**
```python
async def can_use_tool(tool_name: str, tool_input: dict, tool_use_id: str, context: ToolUseContext) -> ToolPermissionDecision:
    # Return ToolPermissionDecision.ALLOW, DENY, or ASK
```

**When canUseTool Is Called:**
`canUseTool` is invoked only when no earlier step in the permission flow resolves the call:
1. Hooks run first; if a hook denies, tool is blocked (does not reach callback).
2. Deny rules (`disallowedTools`) block the call.
3. Ask rules (from settings.json) route to callback.
4. Permission mode check: `bypassPermissions` auto-approves; `acceptEdits` auto-approves file ops; `plan` routes file edits to callback.
5. Allow rules (`allowedTools`) auto-approve.
6. If none matched, `canUseTool` callback is called (except in `dontAsk` mode, which denies instead).

Tools that require user interaction (`AskUserQuestion`, MCP tools marked `_meta["anthropic/requiresUserInteraction"]`) always reach the callback even when an allow rule matches. ([Permissions guide](https://code.claude.com/docs/en/agent-sdk/permissions.md))

**Hooks in SDK:**
The Agent SDK supports `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `SessionEnd`, `UserPromptSubmit` hooks. Hooks are callback functions (not bash scripts like Claude Code CLI). Pass them as `hooks` dict in options. `PreToolUse` hook can return `{ allow: true }`, `{ deny: true }`, or `{}` (pass through). ([Hooks guide](https://code.claude.com/docs/en/agent-sdk/hooks.md))

**Workspace Confinement:**
- **`additionalDirectories`** (both SDKs): List of absolute paths the agent can access in addition to cwd. Tools are confined to cwd + `additionalDirectories`. ([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview.md))
- **`cwd` option**: Sets the working directory for the session. Absolute paths only.
- **Hard Denial of Bash**: Include `disallowedTools: ["Bash"]` with bare tool name (no scoping). This removes Bash entirely from Claude's context so it cannot attempt any Bash calls. ([Permissions guide](https://code.claude.com/docs/en/agent-sdk/permissions.md))

**Sandbox/Isolation:**
The Agent SDK provides no built-in sandbox. Agents run in the user's process and have access to the host OS. The spawned Claude Code subprocess runs with the same privileges as the host process.

**Sources:**
- https://code.claude.com/docs/en/agent-sdk/permissions.md
- https://code.claude.com/docs/en/agent-sdk/hooks.md
- https://code.claude.com/docs/en/agent-sdk/overview.md

## 4. System Prompt Control

**System Prompt Option Forms:**

```typescript
// TypeScript
systemPrompt: string | { type: "preset"; preset: "claude_code"; append?: string; excludeDynamicSections?: boolean }
```

```python
# Python
system_prompt: str | dict  # e.g., {"type": "preset", "preset": "claude_code", "append": "..."}
```

**Preset Forms:**
- **No option**: Uses minimal default (tool-calling only, no Claude Code styling/safety guidance).
- **`{ type: "preset", preset: "claude_code" }`**: Full Claude Code prompt with tool guidance, safety rules, terminal-friendly responses, repo conventions.
- **Preset with `append`**: Adds custom instructions after the preset without removing anything. ([Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md))
- **String**: Custom prompt replaces defaults entirely.

**CLAUDE.md Loading:**
CLAUDE.md is **not** loaded into the system prompt; it is **injected into the conversation** as project context. The SDK reads it when the `project` setting source is enabled. CLAUDE.md content shapes behavior but does not change the system prompt byte string, so two sessions with identical `systemPrompt` but different CLAUDE.md get different full prompts. ([Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md))

**Byte-Stable System Prompt:**
To make the system prompt identical across sessions for cache reuse:
- Use `{ type: "preset", preset: "claude_code", excludeDynamicSections: true }` (available v0.2.98 Python / v0.3.98 TypeScript+). This moves per-session context (cwd, git flag, platform, shell, OS version, auto-memory paths) into the first user message, leaving only static preset + append in the system prompt.
- Tradeoff: environment context has slightly lower weight when in user message vs. system prompt, but cache reuse across machines/directories improves. ([Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md))
- A plain **string** `systemPrompt` is byte-stable by construction (no dynamic sections at all).

**Setting Sources:**
`setting_sources` (Python) / `settingSources` (TypeScript) controls what loads:
- `["project"]`: Loads `.claude/CLAUDE.md` or `CLAUDE.md` from working directory.
- `["user"]`: Loads `~/.claude/CLAUDE.md`.
- Default for `query()` is `["project", "user"]` (both load).
- Setting sources do **not** affect system prompt choice; they control CLAUDE.md and output style loading. ([Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md))

**Sources:**
- https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md
- https://code.claude.com/docs/en/agent-sdk/overview.md

## 5. Streaming & Output

**Message/Event Stream Shape:**

Both SDKs return an async iterable of message objects. Message types include:

| Message Type | Fields | Meaning |
|---|---|---|
| `SystemMessage` (Python) / `type: "system"` (TS) | `subtype: "init"`, `session_id`, `data` | Session initialization; carries session ID |
| `AssistantMessage` (Python) / `type: "assistant"` (TS) | `content: [TextBlock \| ToolUseBlock]` | Claude's reasoning, text output, or tool-use request |
| `ResultMessage` (Python) / `type: "result"` (TS) | `subtype: "success" \| "error_*"`, `result`, `session_id`, `total_cost_usd` | Final result of the session; end of iteration |
| `UserPromptMessage` (Python) / `type: "user_prompt"` (TS) | (permission/approval request) | Request for user input via `canUseTool` or `AskUserQuestion` |

**Partial/Streaming Message Output:**
- **Agent SDK streaming input mode**: Messages are streamed as Claude generates them. Each `query()` iteration yields messages as they arrive. ([Streaming vs. single mode](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode.md))
- **Partial message support**: The Agent SDK iterates over messages as they complete; per this report's verification pass, token-level partial messages are not documented as exposed [ORCHESTRATOR FLAG 2 — verify `includePartialMessages`/equivalent at build; design degrades to per-block rendering]. The Tool Runner (a different product) exposes token-level events via `stream=True`.

**Sources:**
- https://code.claude.com/docs/en/agent-sdk/overview.md
- https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode.md
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner.md

## 6. Model Selection & Error Handling

**Model Selection:**
- **`model` option**: Set `model: "claude-sonnet-5"` (or other model ID) in options. No fallback option exists; if the model is unavailable, the API returns an error. Aliases (`opus`, `sonnet`, `haiku`) are resolved by the CLI subprocess. ([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview.md))

**Error Semantics:**

| `subtype` | Meaning |
|---|---|
| `success` | Agent completed the task |
| `error_max_turns` | Reached `maxTurns` limit |
| `error_max_budget_usd` | Exceeded spend cap |
| `error_tool_use_rejected` | Permission denied on a tool call |
| `error_*` (other) | API error, network failure, model refusal, etc. |

Error details are in the `result` field (plain text description). API errors and rate limits surface as result subtypes; the loop yields the result message and exits. For single-message `query()`, a try/except is recommended because the SDK raises after yielding the final message. ([Sessions guide](https://code.claude.com/docs/en/agent-sdk/sessions.md), [Streaming vs. single mode](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode.md))

**maxTurns:** Limit agentic turns with `max_turns` (Python) / `maxTurns` (TypeScript); hitting it ends the session with `error_max_turns`. The `error_max_budget_usd` subtype implies a corresponding spend-cap option.

**Cost / Usage Reporting:**
The result message includes `total_cost_usd` with the session's total cost, on every result, success or error. ([Sessions guide](https://code.claude.com/docs/en/agent-sdk/sessions.md))

**Sources:**
- https://code.claude.com/docs/en/agent-sdk/overview.md
- https://code.claude.com/docs/en/agent-sdk/sessions.md
- https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode.md

## 7. Packaging Facts

**Package Names & Latest Versions (verified 2026-07-12):**

| SDK | Package Name | Latest Version | Repository |
|---|---|---|---|
| **TypeScript** | `@anthropic-ai/claude-agent-sdk` | `0.3.207` | https://github.com/anthropics/claude-agent-sdk-typescript |
| **Python** | `claude-agent-sdk` | `0.2.116` | https://github.com/anthropics/claude-agent-sdk-python |

**Runtime Requirements:** TypeScript: Node.js 18+. Python: Python 3.10+.

**Claude Code CLI Bundling:**
- **TypeScript**: bundles a native Claude Code binary as an optional dependency; no separate install needed.
- **Python**: automatically bundles the Claude Code CLI; optional `cli_path` option to point at a custom CLI. ([GitHub: Python SDK](https://github.com/anthropics/claude-agent-sdk-python))

**SDK Naming History:** previously "Claude Code SDK", rebranded "Claude Agent SDK" (migration guide: https://docs.claude.com/en/docs/claude-code/sdk/migration-guide).

**Agent SDK vs. Tool Runner:** the Agent SDK runs the full Claude Code agentic loop with built-in tools (Read, Write, Edit, Bash, Glob, Grep, …). The Tool Runner (`client.beta.messages.tool_runner`) runs a loop over tools **you define**, with no built-in tools. Different products.

**Sources:**
- https://github.com/anthropics/claude-agent-sdk-typescript
- https://github.com/anthropics/claude-agent-sdk-python
- https://code.claude.com/docs/en/agent-sdk/overview.md
- https://code.claude.com/docs/en/agent-sdk/quickstart.md

## Risks & Unknowns (verbatim from the research agent)

1. **Cross-session cache behavior not fully documented** — cache hit rate across separate SDK processes with identical prompts is implied, not benchmarked. Verify with API cost attribution in production.
2. **Subprocess overhead not quantified** — measure actual spawn/teardown in the target environment.
3. **Concurrent session limits undocumented.**
4. **Session file compatibility across SDK versions untested/undocumented.**
5. **CLAUDE.md context cost not explicit** (mitigated in our design: `settingSources` disabled for pane sessions).
6. **Subscription OAuth unsupported — API key only.** If a design requires subscription-rate-limit economics, the Agent SDK cannot provide them. Architectural limitation, not a bug.
7. **Session storage in ephemeral environments** — local `~/.claude/projects/...` only; `SessionStore` adapter interface exists without a reference implementation.
8. **Hook/permission interaction edge cases not exhaustively documented.**
9. **`excludeDynamicSections` quality impact unquantified.**
10. **No model fallback option** — application-level retry/fallback needed.

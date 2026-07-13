# SDK auth — empirical test (2026-07-12, post-gate correction)

*User challenged the "Agent SDK is API-key-only" claim in
`2026-07-12-agent-sdk-verification.md` §2. An independent agent tested
it empirically on this machine. The user was right.*

## Verdict

**The claim is FALSE as a technical statement — it is POLICY-ONLY.**
The Python SDK (`claude-agent-sdk` 0.2.116) ran successfully on this
machine's **Claude Max subscription OAuth** with no API key anywhere in
the environment, in both configurations:

| Run | Config | Result |
|---|---|---|
| 1 | Bundled CLI (SDK's own wheel-shipped `claude`) | `AUTH_TEST_OK`, success |
| 2 | `cli_path` → system `claude` 2.1.207 | `AUTH_TEST_OK`, success |

Both with `env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u
CLAUDE_CODE_OAUTH_TOKEN`, no `apiKeyHelper` configured, `primaryApiKey`
null — the only credential on the machine is
`~/.claude/.credentials.json` → `claudeAiOauth` (`subscriptionType:
max`), which the official auth doc lists as **precedence item 6, the
default for Pro/Max/Team/Enterprise users**, applying to "the CLI and
the surfaces that wrap it, **including … the Agent SDK**"
(code.claude.com/docs/en/authentication). The SDK subprocess also fired
the user's own `~/.claude` SessionStart hooks — it reads the same
config tree as interactive `claude`.

The doc sentence the original memo quoted — "Anthropic does not allow
**third party developers** to offer claude.ai login or rate limits
**for their products**" (agent-sdk/overview) — governs third-party
products, not personal use of one's own subscription. `claude
setup-token` / `CLAUDE_CODE_OAUTH_TOKEN` additionally exist as an
explicit subscription path.

Note on `total_cost_usd`: the CLI emits a *computed* token-cost figure
regardless of billing path (subscription runs report it too) — it is
not evidence of billing route. The credential-elimination chain above
is the evidence.

## Consequences for the 09 engine decision

1. **The auth/economics leg of 09 §4.1's cli-vs-sdk comparison is
   VOID.** Both engines are the same binary resolving the same
   credential chain; an SDK-engine pane consumes Max quota exactly as
   `claude -p` does. 09 §4.1 carries a dated correction; the decision's
   surviving grounds are capability (token streaming + `--fallback-model`
   verified live on the `cli` side, unverified/absent per docs on the
   SDK surface) and uniformity/zero-new-dependency — real but much
   closer than originally framed. `canUseTool` remains the sdk engine's
   genuine differentiator.
2. **New footgun the test surfaced (applies to BOTH engines):** the SDK
   by default loads `~/.claude` settings/skills — a **68,011-token
   cache write** per fresh session on this machine. 09 §4.2's emptied
   `--setting-sources` pin was already right; this measurement is why
   it is load-bearing, not hygiene.

## Residual

Whether Anthropic's *terms* bless subscription-quota use for a personal
SDK tool is a legal-interpretation question; the only explicit
prohibition found is the third-party-product clause. Technically, on
this machine: proven twice. GitHub context: claude-agent-sdk-python
#559, claude-agent-sdk-typescript #11 (community friction reflecting
the docs' API-key framing); third-party writeups document the
subscription path working.

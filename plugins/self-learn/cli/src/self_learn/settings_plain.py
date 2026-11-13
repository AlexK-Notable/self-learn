"""Plain words for the settings registry (w33-humane lane 0, S-135).

The settings page groups settings by what a person is trying to do, and
says what each one does in plain words. Those words live here, beside the
registry (:mod:`self_learn.settings`), so the page never keeps its own copy
that drifts the first time a setting is added: an import-time check below
refuses a registry entry with no plain words, and plain words for a name
the registry does not have.

``config get --json`` carries three fields per row from this table:

- ``group``: the id of one of :data:`GROUPS`, in the page's order;
- ``label``: a short plain name ("Read my sessions overnight");
- ``plain``: one or two plain sentences saying what the setting does.

The registry's own ``description`` stays the technical note.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["GROUPS", "GROUP_IDS", "Plain", "plain_for"]


@dataclass(frozen=True)
class Group:
    #: stable id, carried as each row's ``group``
    id: str
    #: the page's heading
    title: str
    #: one plain sentence under the heading ("" for none)
    intro: str
    #: True: the page shows the group closed until opened
    folded: bool


#: The settings page's groups, in page order.
GROUPS: tuple[Group, ...] = (
    Group("runs", "What runs on its own",
          "The jobs that run without you. Turning one off stops it until you turn it on again.", False),
    Group("limits", "Limits on model use",
          "These stop a runaway job. Under a Claude plan the dollar amounts are notional, not charges.", False),
    Group("models", "Which model does what",
          "A model name such as sonnet or opus, or a full model id.", False),
    Group("attention", "How it gets your attention", "", False),
    Group("reading", "What the overnight read looks at",
          "Where it finds your sessions, which ones it skips, and how much of each it reads.", True),
    Group("time", "Time limits and pacing",
          "How long each kind of job may run before it is stopped, and how often jobs start.", True),
    Group("turns", "Turn limits per job",
          "How many steps one model session may take before it is stopped.", True),
    Group("bedrock", "Amazon Bedrock",
          "Only used when the model provider is set to bedrock.", True),
    Group("advanced", "Everything else", "", True),
)
GROUP_IDS: frozenset[str] = frozenset(g.id for g in GROUPS)


@dataclass(frozen=True)
class Plain:
    group: str
    label: str
    plain: str


def _p(group: str, label: str, plain: str) -> Plain:
    return Plain(group, label, plain)


_JOB = {
    "worker": "drafting suggestions for new lessons",
    "miner": "the overnight read of your sessions",
    "analyst": "the one-off suggestion for a single lesson",
    "steward": "the nightly review",
    "overseer": "the weekly check",
    "ask": "the inbox's “Ask about this” agent",
}

_TABLE: dict[str, Plain] = {
    # ---------------------------------------------------------------- runs
    "miner.enabled": _p("runs", "Read my sessions overnight",
        "Each night, read the day's Claude Code sessions and write down new lessons. Off stops every overnight read."),
    "overseer.enabled": _p("runs", "Weekly check",
        "Once a week, re-check the nightly review's decisions and write the weekly report."),
    "steward.enabled": _p("runs", "Nightly review",
        "Each night after the read, decide the new lessons and carry the decisions out. A safety switch."),
    "overseer.skill_writing": _p("runs", "Install the skills it writes",
        "On: the weekly check installs the skills it writes. Off: it only drafts them for you to look at."),
    "overseer.skill_discovery": _p("runs", "Look for new skills",
        "Let the weekly check look for groups of lessons that would make a skill, and decide each idea (one more model call a week)."),
    "overseer.hook_activation": _p("runs", "Turn on warnings it writes",
        "Let the weekly check switch on the warning hooks it writes, after testing them. Off: it places them but leaves them off."),
    "hosts.extra_roots": _p("runs", "Folders outside home it may register",
        "Folders on another disk. The weekly check may register a project inside one of them as a place lessons are written. The folder itself never counts; only what is inside it."),
    "premises.enabled": _p("runs", "Re-check what rules assume",
        "Each day, check whether the facts a rule depends on (a file, a version, a setting) are still true."),
    "premises.backfill_per_night": _p("runs", "Older rules given checks each night",
        "How many older rules with no checks yet the nightly review is offered each night to write them. 0 pauses it."),
    "premises.rotation_days": _p("runs", "Re-read each rule every",
        "How many days pass before a placed rule is re-read to see if it still holds. 0 turns re-reading off."),
    "always_loaded.user_word_budget": _p("runs", "Room for lessons every session loads",
        "The most words of lessons your main instructions file may hold. Over it, the nightly review moves the least-used lessons somewhere cheaper. 0 turns the limit off."),
    "premises.rotation_per_night": _p("runs", "Rules re-read each night",
        "How many rules the nightly review re-reads a night: auto spreads them so each is read once per period."),
    "worker.repair": _p("runs", "Retry a failed draft",
        "When drafting suggestions fails, run one repair round before giving up."),
    "worker.autokick": _p("runs", "Drafting starts itself",
        "Let drafting start a follow-on run by itself when more lessons arrive. A safety switch."),
    "miner.autokick": _p("runs", "Overnight read starts itself",
        "Let the overnight read be started by its watchdog when a run was missed. A safety switch."),
    "miner.engine": _p("runs", "How sessions are read",
        "One model call per session, with tools to read it. The older all-sessions-in-one-digest way was retired on 2026-11-12; an old setting naming it reads as this."),
    "serve.restart_on_new_code": _p("runs", "Restart on new code",
        "Restart the background service between jobs when the self-learn code on disk has changed."),
    # -------------------------------------------------------------- limits
    "miner.max_run_usd": _p("limits", "Most one overnight read may use",
        "No new session is started once the read reaches this, in notional dollars. The rest wait for the next night."),
    "sdk.max_budget_usd": _p("limits", "Most one model call may use",
        "A cap, in dollars, on any single model call. Empty means no limit."),
    "overseer.max_model_calls": _p("limits", "Model calls in one weekly check",
        "The weekly check stops if it makes more calls than this. A guard against a loop, not a budget."),
    "miner.max_sessions_per_run": _p("limits", "Sessions read in one night",
        "The most sessions one overnight read calls a model on. The rest wait for the next night."),
    "miner.parallel": _p("limits", "Sessions read at once",
        "How many sessions the overnight read works on at the same time (at most 8)."),
    "miner.cap_max": _p("limits", "Most lessons found in one night",
        "The overnight read stops writing lessons once it has written this many."),
    "miner.cap_per_session": _p("limits", "Most lessons from one session",
        "The most lessons the overnight read takes from any single session."),
    "miner.pending_gate": _p("limits", "Pause reading when this many wait",
        "The overnight read skips a night while this many lessons are still waiting for a decision."),
    "worker.batch_cap": _p("limits", "Lessons drafted per call",
        "How many lessons drafting prepares in one model call."),
    "steward.packet_size": _p("limits", "Lessons per nightly review call",
        "How many lessons the nightly review decides in one model call. The run itself has no limit."),
    "runs.attempt_cap": _p("limits", "Tries before giving up",
        "How many failed attempts one piece of delegated work gets before it is closed out."),
    # -------------------------------------------------------------- models
    "models.worker": _p("models", "Drafting suggestions", "The model that drafts suggestions for new lessons."),
    "models.miner": _p("models", "Overnight read", "The model that reads your sessions and writes lessons."),
    "models.analyst": _p("models", "One-off suggestion", "The model behind the one-off suggestion for a single lesson."),
    "models.steward": _p("models", "Nightly review", "The model that decides lessons each night."),
    "models.overseer": _p("models", "Weekly check", "The model that re-checks decisions and writes the weekly report."),
    "models.ask": _p("models", "Ask about this", "The model that answers your questions in the inbox."),
    "models.summary": _p("models", "Summaries", "The model that writes a summary when you click Summarise this."),
    # ----------------------------------------------------------- attention
    "worker.no_notify": _p("attention", "Quiet drafting's notifications",
        "On: drafting sends no desktop notifications."),
    "attention.terminal": _p("attention", "Terminal for approved work",
        "The terminal an approved change or a login opens in, such as 'alacritty -e'. Empty: your $TERMINAL, else the first one found."),
    "overseer.broad_removal_threshold": _p("attention", "Tell me when it removes more than",
        "If one weekly check removes more rules than this, it says so in its notification."),
    # ------------------------------------------------------------- reading
    "miner.transcripts_dir": _p("reading", "Where sessions are",
        "The folder the overnight read scans for Claude Code session transcripts."),
    "miner.mined_scheduled_jobs": _p("reading", "Scheduled jobs to read anyway",
        "Sessions of scheduled jobs are skipped, except the jobs named here, separated by commas."),
    "miner.skip_sessions": _p("reading", "Sessions never read",
        "Session ids the overnight read always skips, separated by commas."),
    "refs.transcript_roots": _p("reading", "Where quoted sessions are looked up",
        "The folders searched, in order, when a lesson's quote is checked against its session."),
    "miner.spine_tokens": _p("reading", "Session size before shortening",
        "Above this estimated size, the session engine shortens the agent's own messages. Your typed words are never cut."),
    # ---------------------------------------------------------------- time
    "worker.coalesce_secs": _p("time", "Wait before drafting",
        "Seconds drafting waits for more lessons to arrive before it starts, so several go in one call."),
    "worker.invoke_timeout_secs": _p("time", "Drafting time limit", "Seconds one drafting call may run."),
    "worker.repair_timeout_secs": _p("time", "Repair time limit", "Seconds one repair round may run."),
    "miner.schedule_time": _p("time", "Overnight read starts at",
        "The time of day, as 24-hour HH:MM like 03:30, when the overnight read of your sessions starts. "
        "It may begin up to 15 minutes later, and a missed night is made up when the machine wakes."),
    "miner.reader_timeout_secs": _p("time", "Overnight read call time limit", "Seconds one model call of the overnight read may run."),
    "analyst.timeout_secs": _p("time", "One-off suggestion time limit", "Seconds the one-off suggestion may run."),
    "steward.timeout_secs": _p("time", "Nightly review call time limit", "Seconds one model call of the nightly review may run."),
    "steward.cooldown_secs": _p("time", "Gap between nightly reviews",
        "The least time between two nightly review starts. A failed or held run retries after 2 hours."),
    "overseer.timeout_secs": _p("time", "Weekly check time limit",
        "The least time one phase of the weekly check may run; it grows by 30 seconds per case read."),
    "ask.timeout_secs": _p("time", "Ask about this time limit", "Seconds one answer in the inbox may take."),
    "serve.tick_secs": _p("time", "How often jobs are checked", "Seconds between the background service's checks for due jobs."),
    # --------------------------------------------------------------- turns
    "steward.turns_per_lesson": _p("turns", "Nightly review steps per lesson",
        "A nightly review session may take this many steps for each lesson it is given."),
    # ----------------------------------------------------------- bedrock
    "provider.name": _p("bedrock", "Model provider",
        "anthropic (your Claude login) or bedrock (Amazon Bedrock). A safety switch."),
    "provider.bedrock.region": _p("bedrock", "Bedrock region", "The AWS region for Bedrock calls."),
    "provider.bedrock.profile": _p("bedrock", "Bedrock credentials profile", "The AWS credentials profile for Bedrock calls."),
    "provider.bedrock.models.small_fast": _p("bedrock", "Bedrock small model",
        "The Bedrock model id used for quick side tasks inside a session."),
    # ------------------------------------------------------------ advanced
    "sdk.capture_sessions": _p("advanced", "Keep session copies",
        "Keep a copy of each model session's transcript in the cache, with summarised thinking."),
    "sdk.event_logs": _p("advanced", "Tool logs kept per job", "How many tool-event log files are kept for each kind of job."),
    "sdk.cli_path": _p("advanced", "Claude Code program", "The Claude Code program to run. Empty: see the next setting."),
    "sdk.prefer_installed_cli": _p("advanced", "Use the installed Claude Code",
        "When no program is set, use the Claude Code installed on this machine instead of the one bundled with the SDK."),
    "sdk.model_cli_floors": _p("advanced", "Claude Code version per model",
        "The oldest Claude Code version each model may run with, as model=version pairs."),
    "ledger.actor": _p("advanced", "This machine's name", "The name recorded on this machine's ledger entries."),
    "ledger.glob_probe_budget_s": _p("advanced", "Path check time limit",
        "Seconds spent checking whether one rule's file pattern matches anything."),
}

for _surface, _job in _JOB.items():
    _TABLE[f"sdk.max_turns.{_surface}"] = _p("turns", f"Steps for {_job}",
        f"The most steps one session of {_job} may take.")
    _TABLE[f"provider.bedrock.models.{_surface}"] = _p("bedrock", f"Bedrock model: {_job}",
        f"The Bedrock model id for {_job}; it replaces the model chosen above when the provider is bedrock.")


def _attention_label(kind: str) -> str:
    words = {
        "hold.credentials": "Login problems",
        "hold.money": "Something would cost money",
        "broken.host": "A project folder is broken",
        "broken.stopped": "The ledger is stopped",
        "broken.job": "A job keeps failing",
        "conflict.case-tampered": "A decision file was edited by hand",
        "approved.pending": "Approved work waiting to run",
        "decided.overseer-run": "A weekly check finished",
        "decided.steward-run": "A nightly review finished",
        "decided.always-loaded": "A rule was added to your instructions",
        "decided.hook-activated": "A warning hook was turned on",
        "decided.ask-default": "A question was answered by its default",
        "decided.reading": "A reading of you was recorded",
        "decided.grant-use": "Your standing permission was used",
        "decided.registration": "A project was registered",
        "decided.skill": "A skill was written",
        "decided.notice": "A fault was passed to an agent",
        "decided.withdrawn": "A question was withdrawn",
        "decided.approved-done": "Approved work was carried out",
        "decided.ledger-paths": "Ledger files changed by hand",
    }
    return words.get(kind, kind)


def _attention_rows() -> None:
    from .settings import ATTENTION_CODE_KINDS, attention_kind_key

    for kind in ATTENTION_CODE_KINDS:
        _TABLE[f"attention.class.{attention_kind_key(kind)}"] = _p(
            "attention", f"Inbox: {_attention_label(kind)}",
            "Where this kind of item lands: waits for you (needs-you), shows as decided, stays silent, "
            "or follows its kind's default (table). A “Didn't need me” click sets it.")


def plain_for(name: str) -> Plain:
    """The plain words for registry key *name* (KeyError for an unknown one)."""
    return _TABLE[name]


def _check() -> None:
    """Every registry entry has plain words in a known group, and nothing
    here names a key the registry does not have."""
    from .settings import REGISTRY

    _attention_rows()
    names = {s.name for s in REGISTRY}
    missing = sorted(names - _TABLE.keys())
    extra = sorted(_TABLE.keys() - names)
    assert not missing, f"settings without plain words (add them to settings_plain.py): {missing}"
    assert not extra, f"plain words for unknown settings: {extra}"
    bad = sorted(n for n, p in _TABLE.items() if p.group not in GROUP_IDS or not p.label or not p.plain)
    assert not bad, f"plain words with an unknown group or an empty label/plain: {bad}"


_check()

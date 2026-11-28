"""Windows dispatch profile. Basic capture has no optional dependencies.

Each row names the capabilities one command form needs; a form runs on
Windows only when every capability it needs is switched on in AVAILABLE.

- A plain verb (``status``) has one row.
- A verb with subcommands has a row for every subcommand path
  (``doctor settings``, ``skill script list``). The most specific path
  decides: a subcommand's own row replaces the verb's row, and a
  subcommand with no row of its own is refused (a subcommand added later
  stays off on Windows until someone lists it). The verb's own row is
  what the bare verb (``doctor`` with no subcommand) needs.
- Options that change what a verb needs (the ``teach`` route options)
  have additive rows: the verb's row and every option row must all be
  available.
- A destination chosen at run time (a lesson routed to a hook) cannot be
  read from the command line; :func:`hook_destination_refusal` is the
  run-time check the verbs make before their first write.
"""

from argparse import Namespace

AVAILABLE = {
    "ledger": True,  # general ledger administration beyond basic capture
    "canon": True,
    "hooks": False,
    "sdk": False,
    "background": False,
    "supervisor": False,
    "desktop": False,
}

_L = frozenset({"ledger"})
_LC = frozenset({"ledger", "canon"})

# A command may need several capabilities. Keep each requirement explicit.
REQUIRES = {
    **dict.fromkeys("init host teach show list".split(), frozenset()),
    **dict.fromkeys((
        "bucket canary case config confirm-held confirm-recurrence defer "
        "dismiss-suspect followup grant index link note notice proposal push "
        "reclassify reconcile reconsider rehome reject reopen report rescope "
        "revise select sentinel statement status supersede telemetry undefer user-model"
    ).split(), _L),
    **dict.fromkeys("batch import prune-memory recompile replace reroute retire route skill".split(), _LC),
    "hook": frozenset({"canon", "hooks"}),
    "doctor": frozenset({"ledger", "hooks", "sdk", "supervisor"}),
    **dict.fromkeys("mine overseer steward worker".split(), frozenset({"ledger", "sdk", "background"})),
    **dict.fromkeys("ask premises summarise".split(), frozenset({"sdk"})),
    "serve": frozenset({"background", "supervisor"}),
    "attention": frozenset({"desktop"}),
    # Subcommand rows: the most specific path decides.
    **dict.fromkeys(("host add", "host list"), frozenset()),
    **dict.fromkeys(("host rebind", "host remove", "host set-mode"), _L),
    "host commit-drift": _LC,  # commits a target file in the host repository
    "link contradicts": _L,
    **dict.fromkeys(("hook activate", "hook deactivate"), frozenset({"canon", "hooks"})),
    **dict.fromkeys(("followup done", "followup add"), _L),
    "premises check": frozenset({"sdk"}),
    **dict.fromkeys(("notice list", "notice done"), _L),
    **dict.fromkeys(("telemetry note", "telemetry flush", "telemetry read-observed"), _L),
    "worker kick": frozenset({"ledger", "background"}),
    "worker run": frozenset({"ledger", "sdk"}),
    "overseer run": frozenset({"ledger", "sdk"}),
    **dict.fromkeys(("overseer status", "overseer report", "overseer open", "overseer respond"), _L),
    **dict.fromkeys(("index status", "index build", "index related", "index groups"), _L),
    **dict.fromkeys(("skill write", "skill retire", "skill rename", "skill veto",
                     "skill register", "skill unregister"), _LC),
    "skill list": _L,
    **dict.fromkeys(("skill request build", "skill request change", "skill request withdraw"), _L),
    **dict.fromkeys(("skill reference show", "skill reference check", "skill reference status"), _L),
    **dict.fromkeys(("skill script list", "skill script show"), _L),
    **dict.fromkeys(("skill script draft", "skill script activate", "skill script deactivate"),
                    frozenset({"ledger", "hooks"})),
    "skill script review": frozenset({"ledger", "sdk", "hooks"}),
    **dict.fromkeys(("attention seen", "attention packet", "attention feedback",
                     "attention answer", "attention undo"), frozenset({"desktop"})),
    **dict.fromkeys(("attention run", "attention fix", "attention stop", "attention claim",
                     "attention done"), frozenset({"background", "desktop"})),
    "attention check-login": frozenset({"sdk"}),
    "steward run": frozenset({"ledger", "sdk"}),
    **dict.fromkeys(("mine run", "mine status", "mine tasks", "mine backfill-tasks"),
                    frozenset({"ledger", "sdk"})),
    "canary plant": _L,
    **dict.fromkeys(("case record", "case show", "case list", "case observe", "case receipt",
                     "case index", "case refreeze"), _L),
    **dict.fromkeys(("statement add", "statement list"), _L),
    **dict.fromkeys(("grant add", "grant revoke", "grant list"), _L),
    **dict.fromkeys(("user-model show", "user-model add", "user-model lapse"), _L),
    "doctor settings": _L,
    **dict.fromkeys(("doctor invocation", "doctor miner", "doctor premises"), frozenset({"sdk"})),
    **dict.fromkeys(("config get", "config set", "config unset"), _L),
    "bucket prune": _L,
    "proposal validate": _L,
    # Option rows, additive to the verb's row.
    **dict.fromkeys(("teach --dest", "teach --note", "teach --allow-empty-glob",
                     "teach --rules-path", "teach --allow-unpathed", "teach --follow-up",
                     "teach --unblocks-on", "teach --follow-up-note"), frozenset({"canon"})),
    "teach --route": frozenset({"canon", "sdk"}),
    "teach --hook-input": frozenset({"canon", "hooks"}),
    "--selftest": frozenset({"ledger", "hooks", "sdk", "supervisor"}),
}

# Where argparse stores each subcommand choice, by the form above it.
SUBCOMMANDS = {
    "link": "link_command", "hook": "hook_command", "followup": "followup_command",
    "premises": "premises_command", "notice": "notice_command",
    "telemetry": "telemetry_command", "worker": "worker_command",
    "overseer": "overseer_command", "index": "index_command", "skill": "skill_command",
    "skill request": "request_kind", "skill reference": "reference_command",
    "skill script": "script_command", "attention": "attention_command",
    "steward": "steward_command", "mine": "mine_command", "canary": "canary_command",
    "case": "case_command", "statement": "statement_command", "grant": "grant_command",
    "user-model": "user_model_command", "doctor": "doctor_command",
    "config": "config_command", "host": "host_command", "bucket": "bucket_command",
    "proposal": "proposal_command",
}

# argparse's destinations are authoritative, including abbreviated options
# and explicitly empty string values. Boolean flags have False as their default.
TEACH_OPTIONS = {
    "route": "--route", "dest": "--dest", "note": "--note", "rules_paths": "--rules-path",
    "allow_empty_glob": "--allow-empty-glob", "allow_unpathed": "--allow-unpathed",
    "follow_up": "--follow-up", "unblocks_on": "--unblocks-on", "follow_up_note": "--follow-up-note",
    "hook_input": "--hook-input",
}


def _available(form: str) -> bool:
    return form in REQUIRES and all(AVAILABLE[cap] for cap in REQUIRES[form])


def hint(*forms: str) -> str:
    """A printable addendum for suggested commands this profile cannot run."""
    unavailable = [f"self-learn {form}" for form in forms if not _available(form)]
    if not unavailable:
        return ""
    noun = "is" if len(unavailable) == 1 else "are"
    return f"{' and '.join(unavailable)} {noun} not available on Windows yet.\n"


def command_form(args: Namespace, verb: str) -> str:
    """The most specific subcommand path the parsed arguments name."""
    form = verb
    while form in SUBCOMMANDS:
        sub = getattr(args, SUBCOMMANDS[form], None)
        if sub is None:
            break
        form = f"{form} {sub}"
    return form


def refused(args: Namespace) -> str | None:
    verb = "--selftest" if args.selftest else args.command
    if verb is None:
        return None
    forms = [command_form(args, verb) if verb != "--selftest" else verb]
    if verb == "teach":
        for dest, option in TEACH_OPTIONS.items():
            if dest == "route" and args.dest is not None:
                continue  # An explicit destination bypasses the analyst.
            value = getattr(args, dest)
            if value is not None and value is not False:
                forms.append("teach " + option)
        if args.dest == "hook":
            forms.append("teach --hook-input")
    for form in forms:
        if not _available(form):
            return verb
    return None


def hook_destination_refusal(record_id: str) -> str | None:
    """The refusal for a command that would write, move or remove a lesson's
    hook while the hooks capability is off; ``None`` when hooks are on."""
    if AVAILABLE["hooks"]:
        return None
    return f"{record_id}: the hook destination is unavailable in Windows capture mode"

"""Windows dispatch profile. Basic capture has no optional dependencies."""

from argparse import Namespace

AVAILABLE = {
    "ledger": False,  # general ledger administration beyond capture
    "canon": False,
    "hooks": False,
    "sdk": False,
    "background": False,
    "supervisor": False,
    "desktop": False,
}

# A command may need several capabilities. Keep each requirement explicit.
REQUIRES = {
    **dict.fromkeys("init host teach show list".split(), frozenset()),
    **dict.fromkeys((
        "batch bucket canary case config confirm-held confirm-recurrence defer "
        "dismiss-suspect followup grant index link note notice premises proposal push "
        "reclassify reconcile reconsider rehome reject reopen report rescope "
        "revise select statement status supersede telemetry undefer user-model"
    ).split(), frozenset({"ledger"})),
    **dict.fromkeys("import prune-memory recompile replace reroute retire route skill".split(),
                    frozenset({"ledger", "canon"})),
    "hook": frozenset({"canon", "hooks"}),
    "doctor": frozenset({"ledger", "hooks", "sdk", "supervisor"}),
    **dict.fromkeys("mine overseer steward worker".split(), frozenset({"ledger", "sdk", "background"})),
    **dict.fromkeys("ask summarise".split(), frozenset({"sdk"})),
    "serve": frozenset({"background", "supervisor"}),
    "attention": frozenset({"desktop"}),
    "sentinel": frozenset({"background"}),
    **dict.fromkeys(("host commit-drift", "host rebind", "host remove", "host set-mode"),
                    frozenset({"ledger", "canon"})),
    "teach route": frozenset({"canon", "sdk"}),
    "--selftest": frozenset({"ledger", "hooks", "sdk", "supervisor"}),
}

ROUTE_FLAGS = ("route", "allow_empty_glob", "allow_unpathed")
ROUTE_VALUES = ("dest", "note", "hook_input", "rules_paths", "follow_up", "unblocks_on", "follow_up_note")


def refused(args: Namespace) -> str | None:
    if args.selftest:
        form = verb = "--selftest"
    else:
        verb = form = args.command
        if verb is None:
            return None
        if verb == "host" and args.host_command not in (None, "add", "list"):
            form = f"host {args.host_command}"
        if verb == "teach" and (any(getattr(args, flag) for flag in ROUTE_FLAGS)
                                or any(getattr(args, opt) is not None for opt in ROUTE_VALUES)):
            form = "teach route"
    if form not in REQUIRES or any(not AVAILABLE[cap] for cap in REQUIRES[form]):
        return verb
    return None

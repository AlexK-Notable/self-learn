"""Windows dispatch profile. Basic capture has no optional dependencies."""

from argparse import Namespace

AVAILABLE = {
    "ledger": False,  # general ledger administration beyond basic capture
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
        "bucket canary case config confirm-held confirm-recurrence defer "
        "dismiss-suspect followup grant index link note notice proposal push "
        "reclassify reconcile reconsider rehome reject reopen report rescope "
        "revise select sentinel statement status supersede telemetry undefer user-model"
    ).split(), frozenset({"ledger"})),
    **dict.fromkeys("batch import prune-memory recompile replace reroute retire route skill".split(),
                    frozenset({"ledger", "canon"})),
    "hook": frozenset({"canon", "hooks"}),
    "doctor": frozenset({"ledger", "hooks", "sdk", "supervisor"}),
    **dict.fromkeys("mine overseer steward worker".split(), frozenset({"ledger", "sdk", "background"})),
    **dict.fromkeys("ask premises summarise".split(), frozenset({"sdk"})),
    "serve": frozenset({"background", "supervisor"}),
    "attention": frozenset({"desktop"}),
    **dict.fromkeys(("host commit-drift", "host rebind", "host remove", "host set-mode"),
                    frozenset({"ledger"})),
    **dict.fromkeys(("teach --dest", "teach --note", "teach --allow-empty-glob",
                     "teach --rules-path", "teach --allow-unpathed", "teach --follow-up",
                     "teach --unblocks-on", "teach --follow-up-note"), frozenset({"canon"})),
    "teach --route": frozenset({"canon", "sdk"}),
    "teach --hook-input": frozenset({"canon", "hooks"}),
    "--selftest": frozenset({"ledger", "hooks", "sdk", "supervisor"}),
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


def refused(args: Namespace) -> str | None:
    verb = "--selftest" if args.selftest else args.command
    if verb is None:
        return None
    forms = [verb]
    if verb == "host" and args.host_command not in (None, "add", "list"):
        forms.append(f"host {args.host_command}")
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

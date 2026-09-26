"""2026-09-26 (steward run run-1ca3de428b35): two parts.

1. The secret scan's `high-entropy-base64` rule no longer reads a folder
   path as a secret: a path-shaped run is judged per segment, and a token
   hidden as one segment is still caught.
2. An evidence item whose quote or ref matched the secret scan is dropped
   by the steward's and overseer's runners, with a trace, BEFORE any
   whole-text scan that would otherwise refuse the case (or the run); a
   hit anywhere else still refuses, and a person's `self-learn case
   record` stays strict. The flagged text never reaches the ledger.

Every secret here is built at test time from a random generator: no
literal in this file looks like a live credential. Every scenario runs in
a sandbox ledger under pytest's tmpdir.
"""

from __future__ import annotations

import contextlib
import io
import json
import random
import string

import pytest

from self_learn import cases, cli, steward
from self_learn.overseer import run as overseer_run
from self_learn.scan import redact, scan
from support import make_env, make_home
from test_heading_evidence import (
    HEADING_ITEM,
    KEPT_ITEM,
    KEPT_QUOTE,
    _case,
    _journal_rows,
    _ledger_files_with,
    _steward_writer,
)
from test_overseer_run import (
    _dump,
    _enabled,
    _refused_section,
    _seed_parked_reject,
    _silence_notifications,
)
from test_steward import _dump_yaml, _enable_steward, _head_manifest, _stage_dir
from test_steward_refusals import _dispositions, _notifications, _seed


@pytest.fixture(autouse=True)
def redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


_B64 = string.ascii_letters + string.digits + "+"
_ALNUM = string.ascii_letters + string.digits


def _random_b64(n: int, *, seed: int) -> str:
    """A random base64-charset string with at least one upper, lower and
    digit, and no `/` (so it cannot itself be path-shaped)."""
    rng = random.Random(seed)
    while True:
        out = "".join(rng.choice(_B64) for _ in range(n))
        if (any(c.isupper() for c in out) and any(c.islower() for c in out)
                and any(c.isdigit() for c in out)
                and not all(c in string.hexdigits for c in out)):
            return out


def _fake_github_token(seed: int = 7) -> str:
    rng = random.Random(seed)
    return "gh" + "p_" + "".join(rng.choice(_ALNUM) for _ in range(36))


#: The exact span refused on 2026-09-26 (the `_c` of `drive_c` ends the run).
INCIDENT_SPAN = "/data/SteamLibrary/steamapps/compatdata/3669870/pfx/drive"
INCIDENT_QUOTE = '"cwd":"/data/SteamLibrary/steamapps/compatdata/3669870/pfx/drive_c/users/steamuser"'
INCIDENT_REF = "transcript:00000000-0000-4000-8000-000000000251#L251"


# ------------------------------------------------------------- part 1: scan


def test_the_incident_path_and_other_real_paths_are_not_secrets():
    # Positive control: on master the incident span was exactly this hit.
    assert len(INCIDENT_SPAN) >= 40
    for path in (
        INCIDENT_SPAN,
        "/mnt/Storage/Photos/2024/Vacation/Italy/Florence/Uffizi",
        "/usr/share/texmf/fonts/opentype/public/lm/lmroman10",
        "/var/lib/containers/storage/overlay/l/QWERTYUIOPASD",
    ):
        assert len(path) >= 40 and all(c not in path for c in ".-_ ")
        assert scan(f"cwd was {path} then") == [], path
    assert scan(INCIDENT_QUOTE) == []


def test_a_token_hidden_as_a_path_segment_is_still_caught():
    token = _random_b64(32, seed=1)
    text = f"GET /api/v1/tokens/{token} HTTP"
    hits = scan(text)
    assert [(h.rule, h.span) for h in hits] == [("high-entropy-base64", token)]
    (hit,) = hits
    assert text[hit.start:hit.end] == token
    # redact() uses the same hits: only the segment goes.
    assert redact(text)[0] == "GET /api/v1/tokens/[redacted:high-entropy-base64] HTTP"


def test_the_base64_rule_did_not_go_blind():
    plain = _random_b64(44, seed=2)
    assert [h.rule for h in scan(f"x {plain} y")] == ["high-entropy-base64"]
    # Starts with `/` but has fewer than 3 slashes: still one whole-run hit.
    for shaped in ("/" + _random_b64(43, seed=3), "/" + _random_b64(20, seed=4) + "/" + _random_b64(22, seed=5)):
        hits = scan(f"x {shaped} y")
        assert [(h.rule, h.span) for h in hits] == [("high-entropy-base64", shaped)], shaped


def test_path_segments_keep_the_hex_rule_and_the_other_rules():
    sha40 = "0123456789abcdef" * 2 + "01234567"
    hex48 = "0123456789abcdef" * 3
    # A 40-hex segment in a path passes; a 48-hex one fires hex, once.
    assert scan(f"/objects/pack/tree/{sha40}/blob") == []
    assert [h.rule for h in scan(f"/objects/pack/tree/{hex48}/blob")] == ["high-entropy-hex"]
    # A pattern-rule token as a segment is caught by its own rule.
    token = _fake_github_token()
    assert [h.rule for h in scan(f"/repo/auth/cache/{token}/x")] == ["github-token"]
    # A 19-char non-hex segment passes, a 20-char one fires.
    assert scan("/aa/bb/cc/" + _random_b64(19, seed=6) + "/dd/eeeeeeeeeeee") == []
    assert [h.rule for h in scan("/aa/bb/cc/" + _random_b64(20, seed=6) + "/dd/eeeeeeeeeeee")] == [
        "high-entropy-base64"
    ]


# --------------------------------------------- part 2: the steward's runner


def _secret_item(token: str) -> dict:
    return {"quote": f"export GITHUB_TOKEN_VALUE {token}", "ref": "transcript:0f0f0f0f#L9"}


def test_steward_drops_a_secret_quote_and_the_decision_still_applies(tmp_path, monkeypatch):
    token = _fake_github_token(11)
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-f0000001")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session",
        _steward_writer(_case(rid, [KEPT_ITEM, _secret_item(token)])),
    )

    result = steward.run(home)

    manifest = _head_manifest(home, result.run_id)
    assert manifest["status"] == "complete"
    (case_id,) = manifest["packets"][0]["case_ids"]
    assert _dispositions(home, result.run_id)[rid]["state"] == "applied"
    view = json.dumps(cases.show(home, case_id, evidence_only=False).to_json()["sections"])
    assert KEPT_QUOTE in view  # positive control
    assert token not in view
    row = {
        "ref": "transcript:0f0f0f0f#L9",
        "reason": "a quoted line matched the secret scan (github-token)",
        "rule": "github-token",
    }
    assert manifest["cases"][case_id]["dropped_evidence"] == [row]
    dropped = [r for r in _journal_rows(home) if r.get("status") == "evidence-dropped"]
    assert [(r["case"], r["ref"], r["rule"]) for r in dropped] == [
        (case_id, row["ref"], "github-token")
    ]
    assert token not in json.dumps(dropped)
    # Positive control: the grep reaches the committed run record via the ref.
    assert f"cases/runs/{result.run_id}.json" in [
        p.partition(":")[2] for p in _ledger_files_with(home, "transcript:0f0f0f0f#L9")
    ]
    assert _ledger_files_with(home, token) == []


def test_steward_withholds_a_dropped_items_ref_that_is_itself_flagged(tmp_path, monkeypatch):
    token = _fake_github_token(12)
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-f0000002")
    _enable_steward(home)
    _notifications(monkeypatch)
    item = {"quote": "a clean line", "ref": f"file:/x/{token}#L1"}
    monkeypatch.setattr(
        steward.invocation, "write_session", _steward_writer(_case(rid, [KEPT_ITEM, item])),
    )

    result = steward.run(home)

    manifest = _head_manifest(home, result.run_id)
    (case_id,) = manifest["packets"][0]["case_ids"]
    assert _dispositions(home, result.run_id)[rid]["state"] == "applied"
    assert manifest["cases"][case_id]["dropped_evidence"] == [{
        "ref": cases.WITHHELD_REF,
        "reason": "a quoted line matched the secret scan (github-token)",
        "rule": "github-token",
    }]
    assert _ledger_files_with(home, token) == []


def test_steward_drops_heading_and_secret_items_in_one_pass(tmp_path, monkeypatch):
    """Heading + secret items with one clean item left: both drop. With no
    clean item left, NOTHING drops (one pass) and the case is refused."""
    token = _fake_github_token(13)
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-f0000003")
    data = _case(rid, [KEPT_ITEM, HEADING_ITEM, _secret_item(token)])
    kept, dropped = cases.split_runner_evidence(data)
    assert kept["evidence"] == [KEPT_ITEM]
    assert [row["reason"] for row in dropped] == [
        'a quoted line starts with "## "',
        "a quoted line matched the secret scan (github-token)",
    ]
    only_flagged = _case(rid, [HEADING_ITEM, _secret_item(token)])
    assert cases.split_runner_evidence(only_flagged) == (only_flagged, [])


def test_steward_still_refuses_a_secret_as_the_only_evidence(tmp_path, monkeypatch):
    token = _fake_github_token(14)
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-f0000004")
    _enable_steward(home)
    _notifications(monkeypatch)
    monkeypatch.setattr(
        steward.invocation, "write_session", _steward_writer(_case(rid, [_secret_item(token)])),
    )

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "refused", row
    assert "secret scan" in row["reason"]
    assert cases.list_cases(home, record_id=rid) == []
    assert _ledger_files_with(home, token) == []


def test_steward_still_refuses_a_secret_in_because(tmp_path, monkeypatch):
    token = _fake_github_token(15)
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-f0000005")
    _enable_steward(home)
    _notifications(monkeypatch)
    case = _case(rid, [KEPT_ITEM, _secret_item(token)], because=f"it leaked {token}")
    monkeypatch.setattr(steward.invocation, "write_session", _steward_writer(case))

    result = steward.run(home)

    row = _dispositions(home, result.run_id)[rid]
    assert row["state"] == "refused", row
    assert "secret scan" in row["reason"]
    assert cases.list_cases(home, record_id=rid) == []
    assert _ledger_files_with(home, token) == []


def test_steward_records_the_incident_quote_intact(tmp_path, monkeypatch):
    """The 2026-09-26 shape: with part 1 the Steam path is no secret, so
    nothing is dropped at all and the quote is on the case."""
    env = make_env(tmp_path)
    home = env.ledger
    rid = _seed(home, "lrn-f0000006")
    _enable_steward(home)
    _notifications(monkeypatch)
    incident = {"quote": INCIDENT_QUOTE, "ref": INCIDENT_REF}
    monkeypatch.setattr(
        steward.invocation, "write_session", _steward_writer(_case(rid, [KEPT_ITEM, incident])),
    )

    result = steward.run(home)

    manifest = _head_manifest(home, result.run_id)
    (case_id,) = manifest["packets"][0]["case_ids"]
    assert _dispositions(home, result.run_id)[rid]["state"] == "applied"
    assert manifest["cases"][case_id]["dropped_evidence"] == []
    view = json.dumps(cases.show(home, case_id, evidence_only=False).to_json()["sections"])
    assert "steamapps/compatdata/3669870" in view
    assert [r for r in _journal_rows(home) if r.get("status") == "evidence-dropped"] == []


# -------------------------------------------- part 2: the overseer's runner


def _overseer_phases(monkeypatch, rid: str, parked: str, evidence: list[dict], *,
                     because: str = "too narrow", report_extra: str = "",
                     comment: str = "", raw_case: str | None = None):
    def invoke(spec):
        stage = spec.cwd
        if spec.label == "phase-a":
            _dump(stage / "selection.yaml", {"cases": [], "why_these": "parked intake", "why_stopped": "none blind"})
            _dump(stage / "initial-views.yaml", {"cases": []})
        else:
            headings = [
                "Examined", "Decided in the user's stead", "Hooks", "User model",
                "Catalogue health", "Questions for you", "Refused / could not do",
            ]
            (stage / "report.md").write_text(
                "# draft\n" + "\n".join(f"## {h}\n- none{report_extra}" for h in headings) + "\n",
                encoding="utf-8",
            )
            _dump(stage / "findings.yaml", {"findings": []})
            _dump(stage / "questions.yaml", {"questions": []})
            _dump(stage / "user-model-delta.yaml", {"updates": []})
            _dump(stage / "case-a.yaml", {
                "kind": "resolution", "trigger": "nightly", "outcome": "reject",
                "records": [rid], "scope": "skill:s", "question": "reject it?",
                "supersedes": parked, "evidence": evidence,
                "decision": {"verb": "reject", "because": because, "confidence": "settled"},
            })
            if comment:
                path = stage / "case-a.yaml"
                path.write_text(path.read_text(encoding="utf-8") + f"# {comment}\n", encoding="utf-8")
            if raw_case is not None:
                (stage / "case-a.yaml").write_text(raw_case, encoding="utf-8")
            _dump(stage / "sheet-a.yaml", {"version": 1, "items": [{"id": rid, "verb": "reject"}]})
        return type("SdkLike", (), {
            "ok": True, "rc": 0, "stdout": "", "detail": "", "failure": None, "turns": 1,
        })()

    monkeypatch.setattr(overseer_run.invocation, "write_session", invoke)


def test_overseer_drops_a_secret_quote_and_says_so_in_the_report(tmp_path, monkeypatch):
    token = _fake_github_token(21)
    home = make_home(tmp_path)
    rid, parked = _seed_parked_reject(home, tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    _overseer_phases(
        monkeypatch, rid, parked,
        [{"ref": f"record:{rid}", "quote": "status: pending"}, _secret_item(token)],
    )

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert (result.status, result.code) == ("applied", 0), result
    successors = [r for r in cases.list_cases(home, record_id=rid) if r["case"] != parked]
    assert len(successors) == 1, successors
    successor = successors[0]["case"]
    refused = _refused_section(home)
    assert refused.strip(), "positive control: the section rendered"
    assert (
        f"- case {successor}: evidence from transcript:0f0f0f0f#L9 dropped — "
        "a quoted line matched the secret scan (github-token)"
    ) in refused
    view = json.dumps(cases.show(home, successor, evidence_only=False).to_json()["sections"])
    assert "status: pending" in view  # positive control
    assert token not in view
    assert any(p.endswith(".json") for p in _ledger_files_with(home, "transcript:0f0f0f0f#L9"))
    assert _ledger_files_with(home, token) == []


@pytest.mark.parametrize("where", ["because", "report", "comment", "only-evidence"])
def test_overseer_still_refuses_a_secret_it_may_not_drop(tmp_path, monkeypatch, where):
    token = _fake_github_token(22)
    home = make_home(tmp_path)
    rid, parked = _seed_parked_reject(home, tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    clean = {"ref": f"record:{rid}", "quote": "status: pending"}
    evidence = [_secret_item(token)] if where == "only-evidence" else [clean, _secret_item(token)]
    _overseer_phases(
        monkeypatch, rid, parked, evidence,
        because=f"it leaked {token}" if where == "because" else "too narrow",
        report_extra=f" {token}" if where == "report" else "",
        comment=token if where == "comment" else "",
    )

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status != "applied", result
    assert [r for r in cases.list_cases(home, record_id=rid) if r["case"] != parked] == []
    assert _ledger_files_with(home, token) == []


def test_overseer_refuses_a_secret_carried_out_of_a_dropped_quote_by_an_alias(tmp_path, monkeypatch):
    """The raw file holds the token once, inside the quote that is dropped,
    but a YAML alias carries it into `because`: the case as serialized after
    the drop still holds it, so the run is refused."""
    token = _fake_github_token(23)
    home = make_home(tmp_path)
    rid, parked = _seed_parked_reject(home, tmp_path)
    _enabled(monkeypatch)
    _silence_notifications(monkeypatch)
    raw = (
        "kind: resolution\ntrigger: nightly\noutcome: reject\n"
        f"records: [{rid}]\nscope: skill:s\nquestion: reject it?\nsupersedes: {parked}\n"
        "evidence:\n"
        f"- ref: record:{rid}\n  quote: 'status: pending'\n"
        f"- ref: transcript:0f0f0f0f#L9\n  quote: &leak {token}\n"
        "decision:\n  verb: reject\n  because: *leak\n  confidence: settled\n"
    )
    _overseer_phases(monkeypatch, rid, parked, [], raw_case=raw)

    result = overseer_run.run(home, dry_run=False, no_push=True)

    assert result.status != "applied", result
    assert [r for r in cases.list_cases(home, record_id=rid) if r["case"] != parked] == []
    assert _ledger_files_with(home, token) == []


# ------------------------------------------------------ a person's verb


def test_a_persons_case_record_still_refuses_a_secret_quote(tmp_path, monkeypatch):
    token = _fake_github_token(31)
    home = make_home(tmp_path)
    monkeypatch.setenv("SELF_LEARN_HOME", str(home))
    stage = tmp_path / "stage.yaml"
    _dump(stage, _case("lrn-f0000007", [KEPT_ITEM, _secret_item(token)]))

    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        rc = cli.main(["case", "record", str(stage), "--actor", "human"])

    assert rc != 0
    assert "secret scan" in err.getvalue()
    assert cases.list_cases(home) == []
    # Positive control: the same stage without the flagged item records.
    _dump(stage, _case("lrn-f0000007", [KEPT_ITEM]))
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["case", "record", str(stage), "--actor", "human"]) == 0
    assert len(cases.list_cases(home)) == 1

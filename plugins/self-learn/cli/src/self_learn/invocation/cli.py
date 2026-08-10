"""U-seam Sec 3.5 -- `CliBackend`, the only place `subprocess` is called
for a model invocation.

`B-3`/`B-3a`/`TR7` (NORMATIVE): the transport is reached as
`subprocess.run(...)` / `subprocess.Popen(...)` through the `subprocess`
MODULE at call time -- `import subprocess` at module scope, never
`from subprocess import run`, which would bind the real function at
import time and escape a test's `monkeypatch.setattr(subprocess, "run",
...)` patch.
"""

from __future__ import annotations

import os
import signal
import subprocess

from .contract import LOG_TEMPLATES, TRANSPORT, LogTemplates, Outcome, SessionSpec


class CliBackend:
    """The live backend: spawns a real `claude` process per the transport
    table (Sec 3.5) and renders the surface's log templates (Sec 3.6) on
    every non-`None` failure leg. `write_session` and `text_session` are
    the SAME transport call -- the two operations differ only in what
    the CALLER does with `Outcome.stdout`, never in how the process is
    run."""

    def write_session(self, spec: SessionSpec) -> Outcome:
        return self._run(spec)

    def text_session(self, spec: SessionSpec) -> Outcome:
        return self._run(spec)

    # ----------------------------------------------------------- internals

    def _run(self, spec: SessionSpec) -> Outcome:
        transport = TRANSPORT[spec.surface]
        templates = LOG_TEMPLATES[spec.surface]
        # AV3: settings written, THEN argv built -- order pinned.
        settings_path = (
            spec.cli_settings_writer() if spec.cli_settings_writer is not None else None
        )
        argv = spec.cli_argv_builder(settings_path)

        try:
            if transport.kind == "popen":
                proc = subprocess.Popen(
                    argv,
                    cwd=str(spec.cwd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                try:
                    output, _ = proc.communicate(spec.prompt, timeout=spec.timeout)
                except subprocess.TimeoutExpired as exc:
                    if transport.kills_process_group:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass
                        proc.wait()
                    return self._outcome_timeout(spec, templates, exc)
                rc = proc.returncode
                detail_raw = output or ""
                stdout = output if transport.result_stdout == "merged" else ""
            elif transport.prompt_via_argv:
                proc = subprocess.run(
                    argv,
                    cwd=str(spec.cwd),
                    capture_output=True,
                    text=True,
                    timeout=spec.timeout,
                )
                rc = proc.returncode
                detail_raw = proc.stderr or proc.stdout
                stdout = proc.stdout if transport.result_stdout == "captured" else ""
            else:
                proc = subprocess.run(
                    argv,
                    cwd=str(spec.cwd),
                    input=spec.prompt,
                    capture_output=True,
                    text=True,
                    timeout=spec.timeout,
                )
                rc = proc.returncode
                detail_raw = proc.stderr or proc.stdout
                stdout = proc.stdout if transport.result_stdout == "captured" else ""
        except FileNotFoundError as exc:
            return self._outcome_not_found(spec, templates, exc)
        except subprocess.TimeoutExpired as exc:
            return self._outcome_timeout(spec, templates, exc)
        except OSError as exc:
            if not transport.catches_os_error:
                raise
            return self._outcome_os_error(spec, templates, exc)

        if rc != 0:
            return self._outcome_exit(spec, templates, rc, detail_raw, stdout)
        return Outcome(ok=True, rc=rc, stdout=stdout, detail="", failure=None)

    @staticmethod
    def _format(template: str, spec: SessionSpec, **kwargs: object) -> str:
        return template.format(label=spec.label, **kwargs)

    def _outcome_not_found(
        self, spec: SessionSpec, templates: LogTemplates, exc: BaseException
    ) -> Outcome:
        assert templates.not_found is not None
        spec.log(self._format(templates.not_found, spec))
        return Outcome(ok=False, rc=None, stdout="", detail="", failure="not-found", exc=exc)

    def _outcome_timeout(
        self, spec: SessionSpec, templates: LogTemplates, exc: BaseException
    ) -> Outcome:
        assert templates.timed_out is not None
        timeout_value = spec.timeout_display if spec.timeout_display is not None else spec.timeout
        spec.log(self._format(templates.timed_out, spec, timeout=timeout_value))
        return Outcome(ok=False, rc=None, stdout="", detail="", failure="timeout", exc=exc)

    def _outcome_os_error(
        self, spec: SessionSpec, templates: LogTemplates, exc: BaseException
    ) -> Outcome:
        assert templates.os_error is not None
        spec.log(self._format(templates.os_error, spec, exc=exc))
        return Outcome(
            ok=False, rc=None, stdout="", detail=str(exc), failure="os-error", exc=exc
        )

    def _outcome_exit(
        self,
        spec: SessionSpec,
        templates: LogTemplates,
        rc: int,
        raw_detail: str,
        stdout: str,
    ) -> Outcome:
        assert templates.exited is not None
        rendered = raw_detail
        if templates.detail_strip:
            rendered = rendered.strip()
        if templates.detail_cap is not None:
            rendered = rendered[: templates.detail_cap]
        spec.log(self._format(templates.exited, spec, rc=rc, detail=rendered))
        return Outcome(ok=False, rc=rc, stdout=stdout, detail=raw_detail, failure="exit")

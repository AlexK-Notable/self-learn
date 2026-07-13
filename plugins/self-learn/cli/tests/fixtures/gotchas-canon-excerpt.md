# GOTCHAS — curated operational lessons

Hard-won, reconfirmed lessons worth keeping. Raw captures land in
`GOTCHAS.journal.md`; promote them here by hand once proven.

---

## Storage

### Never edit `.storage/*.json` while HA is running
- **Status:** verified · **Applies when:** all `.storage` edits, every HA version
- **Cause:** HA holds these in memory and rewrites on save/shutdown.
- **Fix:** stop → back up → edit → validate JSON → start → verify. A live edit
  is silently overwritten on the next restart; malformed JSON bricks boot.

### Re-enabling a disabled integration needs core.config_entries edited with HA STOPPED
- **Status:** verified · **Applies when:** any disabled_by:user config entry
- **Cause:** config entries persist disabled_by across restarts.
- **Fix:** stop HA, null out disabled_by, validate JSON, start.

## Lighting

Also documented here in prose: the AL sleep mode gotcha (a stuck sleep_mode
switch forces sleep brightness on an interval timer).

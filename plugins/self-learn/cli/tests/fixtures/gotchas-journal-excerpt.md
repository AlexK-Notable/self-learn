# GOTCHAS — journal (append-only, captured via `ha-note`)

Raw, dated operational lessons. Append here via `ha-note`, never rewrite this
file with an LLM. Promote well-worn entries up into the curated `GOTCHAS.md`
by hand, then leave the journal entry in place (provenance).

---

### 2026-06-02 — A YAML-mode lovelace dashboard key must contain a hyphen or check_config fails: 'Url path needs to contain a hyphen (-)'
- **Status:** verified
- **HA version:** 2026.5.4
- **Cause:** HA requires lovelace.dashboards.<url_path> slugs to contain '-'
- **Fix:** use e.g. 'bedroom-lighting:' not 'lighting:' as the dashboards key (the title can be anything)
- **Repro / verify:** `add lovelace.dashboards with a no-hyphen key, then run check_config`
- **Tags:** lovelace, dashboard

### 2026-06-02 — New entities don't hit on-disk core.entity_registry immediately — HA debounces registry writes, so disk-based inventory lags by minutes
- **Status:** verified
- **HA version:** 2026.5.4
- **Cause:** HA batches/debounces .storage registry saves
- **Fix:** confirm a just-created entity via the live API, not the disk snapshot; the registry flushes later
- **Repro / verify:** `add a light group w/ unique_id, restart, immediately grep core.entity_registry — absent though the state exists`
- **Tags:** inventory, registry

### 2026-06-08 — Re-enabling a disabled integration needs core.config_entries edited with HA STOPPED
- **Status:** verified
- **HA version:** 2026.5.4
- **Cause:** config entries persist disabled_by; a plain restart will not re-enable, and a live .storage edit is clobbered on shutdown
- **Fix:** stop HA, set the entry's disabled_by to null in .storage/core.config_entries, validate JSON, start HA
- **Repro / verify:** `entry shows disabled_by=user in core.config_entries; integration absent until disabled_by cleared`
- **Tags:** storage

### 2026-06-14 — Beacon DHCP IP change silently broke zeroconf-pinned Wyoming STT and wake entries; Piper on the Pi was unaffected
- **Status:** verified
- **HA version:** 2026.5.4
- **Cause:** Wyoming config entries store the IP resolved at zeroconf discovery time; when the DHCP lease moved, the entries kept the stale host
- **Fix:** edit .storage/core.config_entries data.host for the affected entries (HA STOPPED), then start; a config-entry RELOAD does NOT help — host is read from entry data, not re-resolved
- **Repro / verify:** `config_entries/get shows wyoming entries setup_retry while the service ports are listening on the new address`
- **Tags:** wyoming

### 2026-06-15 — Never edit `.storage/*.json` while HA is running
- **Status:** verified
- **HA version:** 2026.5.4
- **Cause:** HA holds these files in memory and rewrites them on save/shutdown, so a live edit is silently clobbered
- **Fix:** stop the container first, back up, edit, validate JSON, start, verify
- **Repro / verify:** `edit a .storage file live, restart HA — the edit is gone`
- **Tags:** storage

### Follow-up — tree floor lamp flares bright then settles on each night-downramp step (date lost when the note was recovered)
- **Status:** unverified  ⚠ re-check before acting
- **HA version:** 2026.5.4
- **Cause:** LEADING HYPOTHESIS (unconfirmed): the ramp sends one turn_on with color+brightness+transition every 60s; the lamp applies color at prior brightness first
- **Fix:** TODO: try brightness-before-color as two ordered calls, or drop transition for these members
- **Tags:** lighting

### 2026-07-03 — AL sleep mode gotcha
- **Status:** verified
- **HA version:** 2026.5.4
- **Cause:** AL applies sleep_brightness (default 1%) every interval while sleep_mode is on; a stray toggle stays stuck
- **Fix:** turn off the instance's sleep_mode switch; the AL main switch's brightness_pct attribute shows AL's computed target
- **Tags:** adaptive-lighting

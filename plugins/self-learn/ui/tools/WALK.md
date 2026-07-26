# UI walk protocol

You are using a web app the way a person would, and writing down what
that was like. You are **not** testing it. There is no pass/fail, no
assertion, no verdict. Your output is a field report: what you did, what
you expected, and what you perceived.

The single rule that makes this worth anything: **do not read the
application's source code.** Not before, not during. If you know what the
code does you will document intent instead of experience, and the report
becomes worthless. A person using this app cannot read its source, and
neither can you. Diagnosis happens later, by someone else.

## Setup

Inject the probe once. Playwright reads the file itself and re-injects it
on every navigation for the rest of the session:

```js
// browser_run_code_unsafe
async (page) => {
  await page.addInitScript({ path: '<REPO>/plugins/self-learn/ui/tools/probe.js' });
  await page.reload();
  return await page.evaluate(() => window.__uiProbe.version);
}
```

Then two calls are available:

- `window.__uiProbe.surfaces()` — everything on this page a person could
  act on, each with a `selector` you can click, plus `perceptible`,
  `container`, `keys`, and `disabled` flags. Also a `coverage` summary and
  a `page` block telling you whether the page continues below the fold.
- `window.__uiProbe.sweep()` — the same thing, but it scrolls the page
  first and measures at every position, then puts the scroll back. Use it
  to find surfaces you cannot currently see.
- `window.__uiProbe.digest({run: '<RUN_ID>'})` — what has *changed* since
  the previous digest call. Returns only the delta.
- `window.__uiProbe.baseline('<RUN_ID>')` — start a fresh comparison
  point. Call this immediately before each action.

Always pass the same `run` id for the whole walk.

## The page is usually taller than the window

Everything the probe reports is scoped to **what is on screen right
now** — that is deliberate, because it is also what a person can see. The
consequence is that you must scroll on purpose, and the probe tells you
when to:

- `coverage.offscreen` — surfaces that are fine in every respect except
  that they are out of view. **A page is not covered until you have
  scrolled to these.** A previous walk called a bucket done having seen
  three of its seven records.
- `sweep()` then marks each of them `scroll_reachable: true` once it has
  actually seen it. Anything still off-screen after a sweep is genuinely
  unreachable, and worth reporting as such.
- `unseen_offscreen` on a digest — meaningful things that changed state
  out of view. **If a digest says `changed_count: 0` and also carries
  `unseen_offscreen`, you have not learned that the control does
  nothing** — only that nothing happened where you were looking. Scroll
  and take another digest before writing that finding down.

## Choosing what to touch

Call `surfaces()` and work through the list. Prefer surfaces where
`perceptible` is true and `container` is absent — a `container` is a
wrapper around the real control, and clicking it does nothing.

Keep a list of what you've visited. `surfaces()` returns an `id` per
surface that stays stable across rows and records; use it. When acting on
a surface changes the page, call `surfaces()` again — new surfaces may
have appeared, and they count too.

Also try the keys. If a control's label says `(g)`, that key is a
surface in its own right — press it and see. `unbound_keys_on_page`
lists keys the page advertises that no visible control claims; those are
worth pressing too.

## The loop, per surface

1. **Write your expectation first, in one line, before you act.** Based
   only on what you can see — the label, its position, what's around it.
   If you cannot predict what it will do, write that instead; "I could
   not tell what this would do" is a real observation about a control.
   Writing it first matters: afterwards you will not be able to tell
   whether you predicted the outcome or rationalised it.
2. `baseline('<RUN_ID>')`.
3. Act — one surface, one action.
4. Sample **twice**, not once:
   - immediately (`digest`, as fast as you can issue it)
   - after it settles (wait ~2s, `digest` again)
   The gap between the two is the point. "Nothing, then something 900ms
   later" is a different experience from "something immediately", and a
   single sample cannot tell them apart.
5. Take a screenshot **with a `filename`** for the record. Only pull an
   image into your context (omit `filename`) when the digest is confusing
   and you need to see the page to describe it.

If a digest call errors with "execution context was destroyed", the page
navigated. That is an observation, not a failure — write it down and
carry on.

## Recording

One block per surface, terse:

```
#003  /bucket/skill/git-hygiene · button "Graduate (g)"
expect  the record leaves the list, with some sign it worked
t+0ms   nothing
t+890ms row gone; strip reads "graduated lrn-*"
note    ~0.9s of no acknowledgement after the click
shot    003-graduate.png
```

Write `note` only when there is something a person would actually
remark on. Most surfaces deserve no note. Do not narrate what the digest
already shows.

## Known sandbox divergences — do NOT report these as defects

The server prints these at startup. They are artefacts of running against
a throwaway sandbox, not problems with the app:

- Pane sessions ("Iterate", "Open bucket chat") show **"Not logged in ·
  Please run /login"**. The sandbox deliberately has no credentials.
- Routing a lesson says "not tracked by chezmoi".
- Pushing says "not pushed — no remote configured".

If you hit one, note that you hit it and move on.

## Boundaries

- Everything you touch is a disposable sandbox. Act freely, including
  destructively — resolving records is the main thing this app does.
- Do not edit any file. Do not run git. Do not read application source.
- Stay on `127.0.0.1`. Do not navigate anywhere else.

## Deliverable

1. A coverage line: how many surfaces existed, how many you exercised,
   and which you could not reach and why. Take the totals from
   `coverage` after a `sweep()`, not from what you happened to see — a
   count that silently omits everything below the fold is worse than no
   count, because it reads as completeness.
2. The per-surface blocks.
3. A short list of the moments where you could not tell what had
   happened. Describe them as experiences, not diagnoses — "I clicked
   Force run and the page reloaded to look identical", not "the worker
   endpoint is broken".

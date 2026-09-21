# jev-evals

Browser-agent evals comparing three models — `jev`, `gemini`, `luna` — on the same decision loop. See [README.md](README.md) for what they measure and how the pieces fit together.

## Harness philosophy

The harness is a pair of hands, not a second brain. Three rules, in order of precedence:

**1. All decision making is delegated to jev.** The harness never decides *what* to do — which element
to act on, whether a dialog should be dismissed, whether a goal is met, whether to give up. It executes
one decision and reports what happened. When a page misbehaves, the fix is almost never harness logic;
it is giving jev truer information so it can decide better. Two bugs in this repo came from breaking
this rule: the harness pressed a consent dialog's own button before jev could choose, and it suppressed
blocking overlays with `pointer-events: none` and reported a phantom `clicked`. Both looked like model
failures and were not.

**2. jev receives the real, unfiltered state.** What jev sees must be what is actually on the page.
Never hide an element because it looks unimportant, never soften an outcome, never report an action as
having succeeded when it did not. A failed click says it failed and names what blocked it. A typed
value that the page discarded says so. Two more bugs came from breaking this rule: `observe.js` dropped
the 1x1 `sr-only` radios that *are* the zero-point filter, making the goal unreachable, and a blocked
click reported `clicked`, so jev waited for something that had never happened.

**3. The harness is as dumb as possible, and every exception is documented.** Mechanics are allowed —
resolving where a click lands, waiting for a load, capturing an outcome. Judgement is not. Anything
that is not purely mechanical is an exception, and an exception must be written down here with its
reason. The current list is short by design:

- **Element pruning** (`prune`, `BROWSER_MAX_CANDIDATES=80`). Ranks by goal-word overlap, dialog
  membership and viewport, then keeps the top N. A budget limit, not a judgement about relevance, but
  it *can* hide a needed control on a very large page. Raise the budget before trusting the ranking.
- **Text excerpt** (`_TEXT_EXCERPT=1800`). jev sees the first 1800 characters of page text. The full
  text is kept on `Observation.full_text` for external scoring, so the scorer is never limited by what
  the model was shown.
- **History window** (`_HISTORY_WINDOW=10`). The last ten actions. Shorter than this and a repeating
  loop becomes invisible to the model deciding whether it is repeating itself.
- **Label proxying** (`observe.js` `proxy`, `Tab._clickable`). A form control with no box of its own is
  measured and clicked through its `<label>`. This is how the browser itself treats a label, and
  without it every `sr-only` radio and checkbox is invisible and unclickable.
- **Overriding an impossible decision** (`loop.py`). If jev names a target that is not in the
  observation, or says `done` while `goal_met` is below 0.5, the loop falls back to its next-best
  action rather than executing a decision that cannot be carried out.
- **Loop guards** (`_repeating`, `_thrashing`, `wait` backoff, `max_steps`, `timeout_s`). The harness
  stops a run that is going nowhere. This is resource control, not task reasoning: it never changes
  what jev is asked, only how long it is allowed to keep asking.

Anything beyond this list should be deleted or promoted to a documented exception. When in doubt,
report more to jev and decide less.

## The eval suites

Two axes: **offline** (our own HTML fixtures) against **online** (real sites), and **unit**
(one behaviour per test) against **e2e** (a whole journey, model in the loop).

**Offline unit** — `make unit`. Fixtures in [evals/offline/pages/](evals/offline/pages/), asserted by
[evals/offline/test_unit.py](evals/offline/test_unit.py). No network, no keys, headless, ~40s. Each
pins one harness contract: a consent gate is reported rather than suppressed, an `sr-only` radio is
observable and clickable, typing does not submit a multi-field form. **Do most iteration here.**

**Online unit** — `make unit-online`. Small assertions against the real Bankrate, freemagazines and
LimeWire pages, ~27s. These exist to keep the offline fixtures honest, so several of them are
*validity guards*: they assert the real page still has the property its fixture models — the
consent gate still appears on a fresh profile, the points input is still a 1x1 box behind a rendered
label. A guard failing does not mean the harness regressed; it means the fixture now models something
the site no longer does. Those assertions fail with `ONLINE EVAL NO LONGER VALID`, and the fix is to
re-inspect the page and update the test and its fixture together.

**E2E** — `make e2e` (alias `make eval`). The two full journeys, download a PDF and find the best
zero-point rate, scored externally. Slow and genuinely flaky. Run to confirm, not to iterate.

```bash
make unit                                  # offline fixtures, fast
make unit-online                           # real pages, incl. fixture validity guards
make e2e                                   # both journeys, all drivers
EVAL=evals/online/test_refinance_e2e.py EVAL_DRIVERS=jev EVAL_RUNS=3 make e2e
```

Every run launches its own Chrome on a free port with a throwaway profile and deletes it afterwards
([evals/local_browser.py](evals/local_browser.py), `fresh_chrome`). That is deliberate: consent and ad
gates are per-profile, so a shared browser lets whichever driver runs first clear the gate for everyone
behind it. Set `EVAL_FRESH_PROFILE=0` to attach to an existing Chrome instead.

`make e2e` sources `.env` itself. Do not run `uv run pytest` directly for online evals — nothing
auto-loads `.env`, so every driver fails to authenticate.

If `uv` is not on PATH it lives at `~/.local/bin/uv`; the Makefile already resolves this.

## When an e2e run fails, capture it before fixing it

An e2e failure is a lead, not a diagnosis. Do not change the harness or the prompt off the back of a
journey trace. Reduce it to the smallest thing that reproduces, in this order:

1. **Offline unit eval first.** Reproduce the failing step as a fixture in
   [evals/offline/pages/](evals/offline/pages/). This is the goal every time: fast, deterministic,
   no network, and it will still reproduce a year from now.
2. **Online unit eval if it cannot be made offline.** Some behaviour only exists on the live site —
   a gate that re-renders itself, server-driven timing, bot detection. Capture it as a single
   problematic *step* in [evals/online/test_unit.py](evals/online/test_unit.py), never as a journey,
   and pair it with a validity guard so the day the site changes is the day the test says so.
3. **Only then change anything.** The new test must fail before the fix and pass after. If it passes
   both ways it is not testing the bug.

Say plainly which of the two you managed, because it matters: an offline reproduction is a fact you
own, an online one is a fact you are renting from someone else's website.

## Replicating a real page as an offline fixture

A fixture is only worth having if it behaves like the page it stands for. Replicate the whole observed
behaviour, not the one part you think is the cause — the first attempt at the LimeWire fixture modelled
the consent gate and left out the modal overlay and the stuck decrypting state, so jev passed it while
failing the real page, and it proved nothing.

**Observe before writing anything.** Drive the real page the way the agent does and watch what happens:

1. **Get the page into the failing state.** These gates are per-profile and often one-shot, so use a
   brand-new profile (`fresh_chrome`, which is what every eval run uses) and take the exact navigation
   path the eval takes rather than a direct URL. If it does not appear, start another fresh profile and
   retry — several times if needed. State that changes between runs is itself a finding worth recording.
2. **Interact with it, do not just read the DOM.** Click each control and record what each one does:
   which dismiss the overlay, which advance it to another one, which release the page, which do nothing.
   LimeWire's CONFIRM opens a second success modal rather than clearing the gate, which a static dump
   never shows.
3. **Watch it, with patience, and after interacting.** A page's behaviour includes how it changes over
   time, and the interesting part often only starts once the gate is cleared. Clear it, then poll for
   minutes, not seconds, recording at each tick what the agent would see: body text, and the target's
   own `getBoundingClientRect()`. Three findings that only a patient watch produces, all from one page:
   the preparing state never resolved across three minutes; the primary action stayed 0x0 the whole
   time, so it was never a click target at all; and neither fact is visible in a single snapshot.
   Whatever you find — resolves after N seconds, never resolves, resolves only after another action —
   is a temporal property, and the fixture reproduces it with the same timing, not as a static page.
4. **Take screenshots** (`tab.screenshot`) whenever the DOM and the rendered page might disagree, and
   when something needs to be shown to a person. A fixture that looks nothing like the real page will
   be spotted by eye long before a test catches it.
5. **Record the shape**: the blocking element's id and class, its `position`, `z-index`,
   `getBoundingClientRect()`, whether it is an overlay covering the target or an inert page underneath,
   every button inside it with its exact accessible name, and whether it lives in an iframe or shadow
   root. Compare `curl` against the DOM: content in one and not the other means client-side rendering.
   Compare headed against headless only after fixing the window size in both.
6. **Reproduce the shape, not the wording.** Same overlay geometry, stacking and z-index, same number
   of steps to clear, same divergence between visible text and accessible name, same layout collapse
   while the gate is up, same timing for anything asynchronous. But write the copy generically: a
   fixture that repeats a real site's vocabulary — its brand, its file name, its exact button text —
   risks testing whether a model recognises that page rather than whether it can reason about the
   structure. Use neutral stand-ins ("Filebox", "quarterly-report.pdf", "Save file", "Preparing").
   Drive state through `document.title` so a test can assert what actually happened.
7. **Check it side by side.** Open the fixture and the real page and compare them by eye before
   trusting the fixture.
8. **Prove it discriminates.** The new test must fail against the old harness and pass against the new
   one, and a model that fails the real page should fail the fixture. If it passes both, the fixture is
   missing whatever actually causes the failure — go back to step 1.

Pair each fixture with a validity guard in [evals/online/test_unit.py](evals/online/test_unit.py)
asserting the real page still has the property being modelled, so the fixture cannot drift out of date.

## Interpreting results

**A failing assertion is often the correct outcome.** Evals are scored externally — a file on disk, or a lender and rate matched against Bankrate's own API — so a run fails when the agent did not actually achieve the goal. That is a result to report, not a bug to fix. Never loosen a scorer to make a run pass.

Report the per-driver table and say plainly which drivers found the answer. `status` is self-reported by the model; `found` is ground truth. When they disagree, `found` wins and the disagreement is worth mentioning.

A single run on a live commercial site proves little — ad gates, cookie banners and bot protection cause failures unrelated to model quality. Use `EVAL_RUNS=3` or more before drawing conclusions, and read the action traces rather than the status column.

## Known failure modes

Each of these has an offline fixture. Reproduce there before changing the harness.

- **Consent and ad gates.** LimeWire shows a Quantcast consent dialog (`#qc-cmp2-container`) and
  freemagazines an ad gate (`.fc-message-root`). Both leave the page *logically* gated: the button is
  clickable but the app refuses to act. Suppressing the overlay defeats the cover, not the gate. The
  harness reports `click blocked: <blocker> is on top of this element` and lets the model decide.
  The ad gate's only control is "View a short ad" — the harness must never press it on its own.
  Fixtures: `consent_gate.html`, `ad_gate.html`, `timed_ad_gate.html`.
- **Controls hidden behind their label.** Bankrate's points filter is four `sr-only` radios, each a 1x1
  input behind a 90x47 label that carries the visible text and takes the click. Observation falls back
  to the label's box, or the control is invisible to the model and the goal unreachable.
  Fixtures: `sr_only_radio.html`, `buried_filter.html`.
- **The form fight.** A model types a value, the page re-renders and discards it. Pressing Enter on a
  multi-field form submits it half-filled, which is what caused it. Fixture: `multi_field_form.html`.
- **Premature done.** A model claims the goal is met on arrival. External scoring catches this.
- **Download path mismatch.** The download eval watches `DOWNLOADS_DIR`; Chrome writes to its profile's
  own directory. On a fresh profile these differ and every run scores "no file".

## Working on this repo

Run `make check` after changes. Follow the existing style: no comments or docstrings, `_` prefix for module-internal names.

Adding a model that generates JSON decisions is one line in `DRIVERS` in [evals/drivers.py](evals/drivers.py) — anything LiteLLM can reach. A different interface needs a class satisfying the `Decider` protocol in [jev_evals/decider.py](jev_evals/decider.py).

Secrets live in `.env`, which is gitignored. Never commit it or echo key values.

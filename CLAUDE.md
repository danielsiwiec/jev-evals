# jev-evals

Browser-agent evals comparing three models — `jev`, `gemini`, `luna` — on the same decision loop. See [README.md](README.md) for what they measure and how the pieces fit together.

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

## Replicating a real page as an offline fixture

When a real site breaks a run, reproduce it offline before fixing anything. Inspect first, guess never:

1. **Catch it live.** These gates are per-profile and often one-shot, so use a brand-new profile
   (`fresh_chrome`) and, if it still will not appear, the exact navigation path the eval takes rather
   than a direct URL.
2. **Inspect the real thing.** Record from the DOM: the blocking element's id and class, its `position`,
   `z-index` and `getBoundingClientRect()`, every button inside it with its exact text, and whether it
   sits in an iframe or shadow root. Check `curl` too: content present in the HTML but absent from the
   DOM means client-side rendering, and vice versa. Compare headed against headless only after fixing
   the window size in both, or layout differences read as rendering differences.
3. **Find the logical gate, not just the visual one.** The question that matters is whether the page
   refuses to act while the gate is unresolved. A fixture that only covers the target will pass against
   a broken harness — the first consent fixture written here did exactly that and proved nothing.
4. **Write the fixture** in [evals/offline/pages/](evals/offline/pages/) reproducing those recorded
   characteristics, and drive state through `document.title` so a test can assert what actually happened.
   Pair it with a validity guard in [evals/online/test_unit.py](evals/online/test_unit.py) asserting the
   real page still has the property you just modelled, so the fixture cannot quietly drift out of date.
5. **Prove it discriminates.** The new test must fail against the old harness and pass against the new
   one. If it passes both, it is not testing what you think.

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

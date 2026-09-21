# Harness philosophy

These are the principles the harness is built to. They are not style preferences: every one of them
was written after a bug that came from breaking it, and each is guarded by evals under `evals/offline/`.
Changing one changes what the evals measure, so change it deliberately and say so.

The harness is a pair of hands, not a second brain. Six rules, in order of precedence:

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

**3. jev's action space resembles a user's.** Click, scroll, type, press a key, drag, refresh, go
back, wait. An action earns its place because a person could perform it with a mouse and a keyboard,
not because it is convenient to express in code. What stays out are verbs that do the *thinking*: no
"dismiss the cookie banner", no "extract the table", no direct navigation to a URL the page does not
link to, no calling a site's API. Those move task reasoning out of the model and into the harness,
which is rule 1 again, and a passing eval then says less about whether the model could drive a browser
it has not seen.

Higher-order actions are welcome where they compose what a user does into one intent, rather than
deciding anything for jev. `submit` — enter a value and press Enter — is one: a person does exactly
that, and making it a single action is what let the harness stop guessing whether Enter should fire.
Picking a date from a calendar widget, choosing from a custom dropdown, or setting a range slider are
good candidates: each is several clicks in the service of one thing a user means to do. The test is
whether jev still chooses the *intent* and the harness only carries out the mechanics. If the action
would decide which date, which option, or whether the step is needed at all, it belongs in the model.
Build them when a goal needs them, and keep the primitives available alongside.

The current set is `click`, `type`, `submit`, `select`, `press`, `scroll_up`, `scroll_down`, `back`,
`refresh`, `wait`, plus `done` and `blocked` as terminal reports rather than page actions.

Remaining gap: `drag` does not exist yet. `select` is also not strictly user-like — a person opens a
dropdown and clicks an option, two clicks, where `select` sets the value through the DOM in one step.
It stays because native `<select>` menus render outside the page and cannot be observed, but it is the
one action in the set a user could not perform as written.

**4. A goal states the user's intent and nothing else.** An objective says what the person wants, in
the words they would use. It does not mention cookie banners, subscription gates, consent dialogs,
ad walls, which control to open, what a filter is called, or how many steps it takes. Translating
intent into correct behaviour on an unfamiliar page is precisely what the model and the harness are
being measured on, so an objective that explains the mechanics marks its own exam. It also quietly
inflates the goal-word overlap ranking, since naming the site's controls makes them score. "Find the
best zero-point refinance rate for a $600,000 loan on a $950,000 property, 800 credit score, zip
96150" is a goal. "Dismiss any cookie gate, then open the points filter, sometimes shown as 'All
points options'" is a walkthrough. If a goal needs a walkthrough to pass, that is the finding.

**5. Every run is inspectable afterwards.** What jev was shown and what the page actually contained are
both written to a trace, one JSON line per step, so a run can be assessed after the fact rather than
re-run and guessed at. Each step records `seen_by_jev` (the exact state passed to the model), `dom`
(the full observation — url, title, alerts, scroll, every element, and the complete page text, not the
excerpt), the decision with its probabilities, and the outcome. This is what makes rule 2 checkable:
when a model does something inexplicable, the trace shows whether it was shown the truth.

Traces land in `.traces/` (`EVAL_TRACE_DIR`), one file per run, named by timestamp and model;
`BrowseResult.trace_path` points at the file. Set `EVAL_TRACE=0` to switch it off. The directory is
gitignored — traces contain whole page texts.

**6. The harness is as dumb as possible, and every exception is documented.** Mechanics are allowed —
resolving where a click lands, waiting for a load, capturing an outcome. Judgement is not. Anything
that is not purely mechanical is an exception, and an exception must be written down here with its
reason. The current list is short by design:

- **Observation budget** (`prune` to `BROWSER_MAX_CANDIDATES=80`, `_TEXT_EXCERPT=1800`,
  `_HISTORY_WINDOW=10`, a 400-element cap in `observe.js`, names clipped to 80–120 characters). jev
  sees a slice of a large page, ranked by goal-word overlap, dialog membership and viewport. This is
  the biggest live violation of rule 2 and it is a budget, not a judgement: a needed control on a very
  large page can fall outside it. **Being replaced by pagination**, so jev is told more exists and can
  ask for it, instead of the harness choosing what matters. The full page text is already kept on
  `Observation.full_text` and in every trace, so scoring is never limited by what the model was shown.
- **Label stand-in** (`observe.js` `standIn`). A form control styled `sr-only` has no box of its own,
  so the `<label>` that a person actually sees and clicks is observed and acted on in its place. The
  browser forwards a label click to its control, so this is the mechanically correct target, not a
  substitution: without it every `sr-only` radio and checkbox is invisible and the goal unreachable.
- **Overriding `done`** (`_DONE_AGREEMENT`, `loop.py`). If jev answers `done` while its own `goal_met`
  is below 0.5, the loop takes the next-best action instead. Kept deliberately: the two answers are
  evaluated in isolation and can contradict each other, and this is the cheapest guard against
  declaring victory on arrival.
- **Loop guards** (`_no_progress`, `stuck >= 0.8`, `wait` backoff, `max_steps`, `timeout_s`). The run
  stops when nothing is changing. Resource control, not task reasoning: it never alters what jev is
  asked, only how long it may keep asking. The harness also picks the `wait` duration, which jev
  arguably should choose.
- **Native JS dialogs** (`Tab._on_dialog`). An `alert` or `confirm` blocks the page until it is
  handled, so it cannot be left open for jev to decide about. It is dismissed and reported verbatim in
  the outcome.

Anything beyond this list should be deleted or promoted to a documented exception. When in doubt,
report more to jev and decide less.

**Never add harness smarts silently.** Any new heuristic, ranking, scoring, filtering, retry or
fallback — anything where the harness is deciding rather than carrying out — gets raised with the
user before it goes in, with what it does and what it would replace. Restoring a heuristic that was
removed counts, and so does keeping one that a refactor happened to preserve. The user decides
whether it stays; the default answer is that jev gets the raw facts and makes the call. This rule
exists because such logic tends to arrive quietly as part of fixing something else, and is then
indistinguishable from the model's own behaviour in every eval that follows.

## How these are guarded

- Rules 1, 2 and 6 (delegation, unfiltered state, dumbness) are checked by the harness contracts in
  [evals/offline/test_unit.py](../evals/offline/test_unit.py): a blocked click is reported rather than
  suppressed, an ad gate is never auto-accepted, an ordinary dialog is left alone, `back` does not
  claim to have moved when it has not.
- Rule 3 (action space) is visible in `ACTIONS` in [jev_evals/actions.py](../jev_evals/actions.py).
  Adding a verb that decides something is the failure mode to watch for.
- Rule 5 (inspectability) is [jev_evals/trace.py](../jev_evals/trace.py); every run writes what jev
  saw and what the DOM held.

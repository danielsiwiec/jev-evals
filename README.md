# Peregrine

A browser agent for fast, structured decision models — the kind that return typed answers with
probabilities rather than text. Peregrine gives such a model eyes and hands: it turns a live page into
structured state, carries out one chosen action, and reports honestly what happened. It decides
nothing itself.

The name is the bird and the word: *peregrinus*, the traveller, and the fastest animal alive. Both
halves are the point — moving through the web, quickly.

```
goal ──▶ observe the page ──▶ model picks one action ──▶ perform it ──▶ report the outcome ──┐
             ▲                                                                                │
             └────────────────────────────────────────────────────────────────────────────────┘
```

Every step, the model sees the current page — url, title, text, interactive elements, open tabs,
recent actions — and answers what the single next action should be: click, type, submit, select,
press, scroll, back, refresh, close a tab, show more, wait, done, blocked. Peregrine performs it and
observes again.

The harness is deliberately dumb. What it may and may not decide is written down in
[specs/harness-philosophy.md](specs/harness-philosophy.md), and most of those rules exist because
breaking one produced a bug that looked like a model failure and was not.

It ships with evals that compare models on the same loop — currently [Jev](https://typesafe.sh),
Gemini Flash Lite and Luna. Only the model changes between drivers, so differences in the results are
differences between models rather than between harnesses.

Scoring is external. A run counts as a success only if the world changed — a file on disk, or an
answer matching Bankrate's own API. A model saying it succeeded proves nothing.

## Specs

[specs/](specs/) holds the principles this project is built on, kept separate from the code because
they outlast it. They are not documentation of what the code happens to do — they are what it is held
to, and most were written after a bug caused by breaking them.

| spec | guards |
|---|---|
| [harness-philosophy.md](specs/harness-philosophy.md) | that decisions belong to the model and not the harness: jev decides, jev sees the real unfiltered state, the action space stays what a person could do, goals state intent only, every run is inspectable, and any logic the harness owns is listed as an exception |
| [eval-approach.md](specs/eval-approach.md) | that failures are reproduced before they are fixed, offline where possible, and that fixtures replicate a real page faithfully rather than the part we assume is the cause |
| [decisions.md](specs/decisions.md) | choices that are easy to reverse by accident, with the evidence that produced them |
| [known-failure-modes.md](specs/known-failure-modes.md) | the failures seen so far and the fixture covering each |
| [targets.md](specs/targets.md) | what pass rate, cost and latency should be, and how many runs a claim about them needs before it means anything |
| [bu-bench-handoff.md](specs/bu-bench-handoff.md) | how to rank Peregrine against other agents on an external benchmark, and why that stays separate from `evals/` |

A change that contradicts a spec is a change to the spec: update it in the same commit and say what
the new evidence is. When a spec and the code disagree, the spec is the intent and the code is the bug.

## The drivers

| driver | model | how it decides | cost |
|---|---|---|---|
| `jev` | `jev-latest` | hosted classification API; scores fixed option sets, generates no text | $0.042/M in, output free |
| `gemini` | `gemini/gemini-3.1-flash-lite` | generates a JSON decision against a strict schema | $0.25/M in, $1.50/M out |
| `luna` | `gpt-5.6-luna` | generates a JSON decision against a strict schema | $0.20/M in, $1.20/M out |

All three implement the same `Decider` protocol in [`peregrine/decider.py`](peregrine/decider.py) and run through the same [`run_goal`](peregrine/loop.py) loop.

## The evals

**`test_refinance.py`** — find the best zero-point mortgage refinance rate on Bankrate for a $600k loan on a $950k property, 800 credit score, zip 96150.

The scorer calls the endpoint Bankrate's own rate table uses (`explorers-rate-tables.bankrate.com/api/home-lending`, `pointsRange=ZERO`) to get the live correct answer, then requires the agent to name **both the lender and the rate**. Ground truth is fetched per run, so it stays valid as rates move.

This matters: the unfiltered page already shows rates, so a scorer that only looked for "a plausible rate" passed agents that never applied the points filter. Naming the right lender is not guessable.

**`test_download.py`** — download the newest Economist USA PDF from freemagazines.top. Scored on a file appearing on disk with a stable size and no `.crdownload` — the agent's own "done" is ignored.

## Setup

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and Chrome.

```bash
uv sync
uv run playwright install chromium
cp .env.template .env   # then fill in your keys
```

Start Chrome with remote debugging. A separate profile keeps your own browser untouched:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-eval \
  --no-first-run --no-default-browser-check
```

> The download eval checks `DOWNLOADS_DIR` (default `~/Downloads`), but Chrome writes to whatever its **own** profile is configured to use. On a fresh profile these differ, and every run then scores "no file". Point Chrome's download directory at the same place, or set `DOWNLOADS_DIR` to the profile's.

## Running

```bash
make eval                                    # all drivers, both evals
uv run pytest evals/test_refinance.py -m eval -s
EVAL_DRIVERS=jev,luna EVAL_RUNS=3 make eval  # subset, repeated
```

Each run prints a per-run table and a per-driver summary (success rate, mean seconds, mean cost, mean calls, mean model latency), followed by the full action trace for every run.

| variable | default | meaning |
|---|---|---|
| `EVAL_DRIVERS` | `jev,gemini,luna` | which drivers to run |
| `EVAL_RUNS` | `1` | repetitions per driver |
| `EVAL_MAX_STEPS` | `40` | step budget per run |
| `EVAL_TIMEOUT_S` | `300` | wall-clock budget per run |
| `EVAL_GEMINI_MODEL` | `gemini/gemini-3.1-flash-lite` | override the Gemini model |
| `EVAL_LUNA_MODEL` | `gpt-5.6-luna` | override the Luna model |
| `BROWSER_CDP_HTTP` | `http://localhost:9222` | Chrome CDP endpoint |
| `DOWNLOADS_DIR` | `~/Downloads` | where the download eval looks for the file |

Keys go in `.env`: `TYPESAFE_API_KEY` (jev), `GEMINI_API_KEY` (gemini), `OPENAI_API_KEY` (luna). Evals skip without `TYPESAFE_API_KEY`.

`make test` runs the non-eval tests; `make check` formats and lints.

## Reading the results

These run against live commercial sites with ad gates, cookie banners and bot protection. A single run tells you little — a failure may be a captcha, not a model. Use `EVAL_RUNS=3` or more before concluding anything, and read the action trace rather than the status column.

Two failure modes worth recognising in the trace:

- **The form fight.** A model writes a value, the page re-renders and discards it, and the model writes again. It shows up as the same element ref repeating with different values while `stuck` climbs. The loop's repeat detector looks for an *unchanged* page, so a page that keeps changing without progressing slips past it.
- **Premature done.** A model reports the goal is met on arrival. `goal_met` is only trusted from deciders that report calibrated probabilities (`Decider.calibrated`); for the rest, only an explicit `done` action ends a run. External scoring catches this regardless.

## Layout

```
specs/            the principles above
evals/offline/    HTML fixtures and the unit evals that pin harness behaviour
evals/online/     unit evals against real pages, plus the two e2e journeys
peregrine/        the harness: observation, decision loop, browser control, tracing
```


```
peregrine/     the loop, page driver and deciders (extracted from synthia)
  loop.py        run_goal: observe, decide, act, repeat
  decider.py     JevDecider, LlmDecider and the Decider protocol
  actions.py     the action set, observations, question building
  page.py        CDP/Playwright tab driver
  jev.py         Jev API client and usage accounting
evals/         the evals themselves
  drivers.py     driver registry; one entry per model
  bankrate_api.py  ground truth for the refinance eval
  report.py      result tables
```

To add a model that generates JSON decisions, add one line to `DRIVERS` in [`evals/drivers.py`](evals/drivers.py) — anything LiteLLM can reach, with pricing read from its model table. A model with a different interface needs a class satisfying the `Decider` protocol.

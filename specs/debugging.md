# Debugging a run

Three records exist for every run, and they answer different questions. Reach for them in this order.

## 1. The step trace — what the harness believes happened

Written for every run to `.traces/<timestamp>-<model>-<id>.jsonl`, one JSON line per step. It holds
both halves of what rule 2 promises: `seen_by_jev` is the exact state passed to the model, and `dom`
is the full observation behind it — url, title, alerts, scroll, every element, and the complete page
text rather than the excerpt. Also the decision with its probabilities, and the outcome.

```bash
EVAL_TRACE=0                 # off; on by default
EVAL_TRACE_DIR=/tmp/traces   # somewhere other than .traces/
```

Reading one:

```python
import json

recs = [json.loads(l) for l in open(".traces/<file>.jsonl")]
steps = [r for r in recs if r["kind"] == "step"]
steps[0]["seen_by_jev"]["elements"]  # what the model could choose from
steps[0]["dom"]["elements"]  # everything that was actually there
```

The filename carries a per-run suffix because parallel runs start in the same second; without it
several runs interleave into one file and the step numbers repeat.

## 2. The efficiency record — what each action was for

Appended to the same file as `{"kind": "efficiency"}` when judging is on. It carries the label per
action (`progressing`, `redundant`, `overcontinuing`, `misdirected`, `exploratory`, `failed`) and
the breakdown. A low efficiency score says work was wasted; this says which actions and in what way.

```python
e = next(r for r in recs if r["kind"] == "efficiency")
e["breakdown"]  # {"progressing": 7, "redundant": 2, ...}
[a for a in e["actions"] if a["label"] != "progressing"]
```

`EVAL_EFFICIENCY=0` turns judging off.

## 3. The browser trace — what actually happened

Everything above is the harness's account of itself. When that account is wrong there is nothing to
check it against, and it has been wrong: a click reported as landing while an overlay took it, a
value reported as typed into a field that discarded it.

`EVAL_BROWSER_TRACE=1` records Playwright's own trace next to ours, written by the browser: DOM
snapshots, a screencast, network requests and console messages. One run produced 260 frame
snapshots, 156 screencast frames and 27 console messages.

```bash
EVAL_BROWSER_TRACE=1 EVAL_RUNS=1 EVAL_DRIVERS=jev make e2e
playwright show-trace .traces/<file>.browser.zip
```

Off by default: about 12 MB per run. Use it when the harness's story does not add up, and compare
the two step for step.

## Screenshots per step

`EVAL_TRACE_SHOTS=1` writes before and after PNGs for each step into `.traces/<run>/`, referenced
from each step record. Cheaper than a full browser trace and often enough — a screenshot is what
showed that a cookie banner was covering the filter panel while the trace showed the dismiss button
missing from jev's view.

## Watching it happen

```bash
EVAL_HEADLESS=0 BROWSER_KEEP_FOCUS_ON=Code EVAL_PARALLEL=1 EVAL_RUNS=1 make e2e
```

A headed window cannot be hidden on macOS — every off-screen `--window-position` is clamped back
onto the desktop — but `BROWSER_KEEP_FOCUS_ON=<app>` hands focus back each time Chrome grabs it, so
the run does not sit on top of what you are doing. Serial runs keep focus reliably; four in parallel
leak occasionally, because four Chromes launching at once outrace the hand-back.

## Every switch

| variable | default | what it does |
|---|---|---|
| `EVAL_TRACE` | `1` | write the step trace |
| `EVAL_TRACE_DIR` | `.traces` | where traces go |
| `EVAL_TRACE_SHOTS` | `0` | before/after screenshots per step |
| `EVAL_BROWSER_TRACE` | `0` | Playwright's own trace, ~12 MB a run |
| `EVAL_EFFICIENCY` | `1` | judge what each action was for |
| `EVAL_HEADLESS` | `1` | headless Chrome |
| `BROWSER_KEEP_FOCUS_ON` | unset | app to hand focus back to, macOS only |
| `BROWSER_ALLOW_FOCUS` | `0` | let the harness raise the browser window |
| `EVAL_PARALLEL` | `1` | how many runs in flight |
| `EVAL_RUNS` | `1` | runs per driver |
| `EVAL_DRIVERS` | `jev,gemini,luna` | which drivers |
| `EVAL_FRESH_PROFILE` | `1` | a throwaway Chrome per run |
| `EVAL_WINDOW` | `1440,900` | window size; the default 800x600 hides Bankrate's form |
| `EVAL_MAX_STEPS` | `40` | step budget per run |
| `EVAL_TIMEOUT_S` | `300` | wall clock per run |
| `TEXT_MODEL` | `gemini/gemini-3.1-flash-lite` | model for `compose`; empty disables it |
| `CHROME_BINARY` | macOS Chrome | where Chrome lives |

`.traces/` is gitignored: traces carry whole page texts.

# Targets and how many runs it takes to believe them

Three things are measured on every e2e eval: **pass rate** (ground truth, not self-report), **cost**
per run, and **latency** per run. This document says what the targets are, and — more importantly —
how many repetitions a claim about them needs before it means anything.

## Why the sample size matters more than the target

The most common mistake here is reading a 4-run batch as a result. Our own data shows why: on one
unchanged harness, consecutive 4-run batches scored 1/4 and then 4/4. Both were "real"; neither was
informative.

For a pass rate, a run either succeeds or not, so a batch of *n* runs is a binomial sample. The 95%
confidence interval on 14/18 (our current data) is:

```
observed 77.8%   95% CI [52.4%, 93.6%]   width 41 points
```

Eighteen runs and the honest claim is "somewhere between half and almost always". Any conclusion
narrower than that interval is being read out of noise.

**Runs needed for a given margin at 95% confidence:**

| margin | n (worst case, p=0.5) | n (at p≈0.78) |
|---|---|---|
| ±20% | 25 | 17 |
| ±15% | 43 | 30 |
| ±10% | 97 | 66 |
| ±5% | 385 | 264 |

Use the worst-case column when the true rate is unknown, which it usually is.

**Practical rule.** Development iteration uses `EVAL_RUNS=4`, and a 4-run batch is a smoke test: it
can show something is badly broken, and it cannot show something is better. Any claim that a change
improved or regressed the pass rate needs **n=25 minimum**, and a claim of a specific rate needs
**n=43**. A change that looks like 3/4 → 4/4 is not evidence of anything.

**A cheaper alternative for comparisons.** When asking "is B better than A", a paired design beats
two independent batches: run both arms against the same task on the same profile and compare
per-task outcomes with McNemar's test. It removes site variance, which is the largest noise source
here, and typically needs a third to a half of the runs.

## Cost

Cost is well behaved: cv = 0.32, so **n=10 gives ±20% of the mean and n=40 gives ±10%**. Cost claims
are cheap to make and should be held to the tighter bound.

Current, on the refinance e2e with jev (n=18): **mean $0.0033, median $0.0030, p90 $0.0055**.

**Target: ≤ $0.005 per run, mean, at n≥10.** A change that doubles cost for a pass-rate improvement
inside the confidence interval is not a win.

## Latency

Latency is badly skewed: **mean 12.6s against a median of 8.4s, cv = 0.92, p90 40.3s**. The mean is
dragged by a tail of runs that hit a gate or thrash before the no-progress guard fires.

Quoting a mean here is misleading, and pinning one is expensive — ±20% of the mean needs n=82. So:

- **Report the median and p90, not the mean.** The median describes a normal run; the p90 describes
  the tail worth fixing.
- **Target: median ≤ 10s, p90 ≤ 45s**, at n≥25 (the same batch that supports the pass-rate claim).
- A regression in p90 with a steady median means a new failure mode in the tail, not a slowdown.

## Running a batch big enough to matter

Runs are independent and each owns a throwaway Chrome, so they fan out. `EVAL_PARALLEL=n` puts at
most n in flight:

```bash
EVAL_PARALLEL=5 EVAL_RUNS=25 EVAL_DRIVERS=jev EVAL=evals/online/test_refinance_e2e.py make e2e
```

That is about 70 seconds for n=25 against roughly 5 minutes serial, which is what makes a
statistically meaningful batch a routine thing to run rather than an event. Keep concurrency at or
below 5: each run is a full Chrome, and the sites are shared.

Comparative runs (driver against driver) should stay serial. Concurrency adds contention that is not
part of what is being compared.

**A headed window is always visible, but it need not hold focus.** Every off-screen
`--window-position`, positive or negative, is clamped back to the top-left of the desktop — measured
at `0, 33` for `-2400,0`, `5000,0` and `-3000,-3000` alike. The window appears and no flag prevents
it.

Focus is a different matter. Chrome takes the front on launch and again every time a tab opens, so
suppressing `bring_to_front` was never enough. `BROWSER_KEEP_FOCUS_ON=<app>` names an application to
hand focus straight back to, at every point Chrome grabs it:

```bash
BROWSER_KEEP_FOCUS_ON=Code EVAL_HEADLESS=0 EVAL_RUNS=2 make e2e
```

Measured by sampling the frontmost process every two seconds: serial headed runs kept focus on Code
for 14 of 14 samples across two runs. Four in parallel leaked 2 of 16 samples, because four Chromes
launching at once outrace the hand-back. macOS only, no-op unless set, and never allowed to fail a
run.

Headless remains the default and costs nothing: at n=25 both modes scored 22/25, with medians of 8.0s
and 8.6s. Use headed when you want to watch; use headless when you want the machine.

## Efficiency

Pass rate says whether the goal was reached. Efficiency says how much of the work was wasted getting
there, and what kind of waste it was.

After every run, jev is handed the whole trace and asked, one `Choice` per action, **what that action
was for** — judged with hindsight against the full sequence:

| label | meaning |
|---|---|
| `progressing` | filled a field the goal names, opened or applied a control it needs, revealed information it requires |
| `redundant` | repeated something already done, or re-entered a value the field already held |
| `overcontinuing` | the goal was already answerable and this went on anyway |
| `misdirected` | acted on a field or control the goal never mentions |
| `exploratory` | looked around without committing: scrolling or paging |
| `failed` | did not do what it set out to do |

Efficiency is the share labelled `progressing`. One call per run, about $0.00006, on unless
`EVAL_EFFICIENCY=0`.

**Labels beat a score, measurably.** The first version asked for a 0-1 usefulness rating. Jev is not
decisive about that: a plainly useful action and an aimless one both landed near 0.75, so the answer
depended entirely on where the threshold sat, and a single action straddling it swung a run's
efficiency from 8% to 25%. Asked to *name* what an action was for, jev answers at 0.99-1.00
confidence and gives the same twelve labels on three consecutive runs of the same trace. The
classifier is being used for what it is good at.

**The report says what the browser did, never whether it was right.** An early version ended each
action with "it worked", which asserts success the harness cannot know: a value typed into the wrong
field was carried out and still wasted. It measurably over-credited — clicking through to a lender's
offer page scored 0.78 with it and 0.21-0.48 without. Actions now end with the mechanical fact: "the
click landed", "the text went in".

**The judge reads a trace written for it.** The loop's debugging history shows a field's value
*before* typing, which reads as the result, so a redundant retype looked more successful than the
action that filled the field. Element refs are reassigned every observation, so the same field
carries a different number each step. `BrowseResult.narrative` renders intent and effect instead:
*"typed '950000' into 'Property value' which held '830,000'"* against *"...which already held that"*.

The state also carries the values the goal supplies, and the step where the run came closest to
believing it was finished. An absolute threshold on `goal_met` was tried and marked nothing: it peaks
around 0.46 even on runs that succeed, so the peak is used instead.

**The eval says when the answer was already on screen.** Only the eval knows the right answer, so
only it can say when further work stopped being necessary. Each step's page text is kept on
`BrowseResult.screens`, and the refinance eval scans it for the lender and rate its scorer already
looks for, then tells the judge the first step where both were visible. Judging is deferred until
after scoring for this reason. The step number alone was not enough: it left the judge to do the arithmetic for every action, and
`overcontinuing` only reached 4%. Saying it on the action itself -- *"[the answer was already on
screen before this]"* -- puts the right question in front of the judge, and it reached **22%**. On a
synthetic trace the same change takes a run from 100% progressing to 62%, flipping the three actions
after the answer appeared.

**Leaving the page is said plainly too.** Opening a new tab is the most consequential thing an action
can do and the raw outcome buried it behind a hundred characters of tracking URL. It now reads *"this
opened a NEW TAB and the run carried on there, away from the page it was on"*.

Measured at n=8: **42% progressing**, 22% overcontinuing, 20% exploratory, 13% redundant, 2%
misdirected. **Target: ≥ 40% progressing**, at the same n=25 as the pass rate. Overcontinuing at 22%
is now the largest kind of waste and the clearest thing to fix. Earlier figures of 70% and 37% came from the score-based version and are not the same
measurement.

**Known bias: on the refinance eval, jev is grading its own work.** For the other drivers it is an
independent judge; for jev it is not. A second judge model would settle it and has not been tried.

Per-action labels are written to the run's trace as an `efficiency` record, because the breakdown is
the part worth acting on: 17% redundant points at the form fight, and `overcontinuing` at the run
that will not stop once the answer is on screen.

## Current targets

Measured on `evals/online/test_refinance_e2e.py` with the `jev` driver, current harness (n=18):

| metric | observed | target | n for the claim |
|---|---|---|---|
| pass rate (`found`) | 88.0% [68.8–97.5] | **≥ 75%** | 25 |
| cost per run | $0.0029 | **≤ $0.005** | 10 |
| latency median | 8.0s | **≤ 10s** | 25 |
| latency p90 | 17.2s | **≤ 45s** | 25 |
| efficiency (progressing) | 42% (n=8) | **≥ 40%** | 25 |

Measured at n=25, headless, five at a time. Two independent n=25 batches, one headed and one
headless, both scored 22/25, which is the first pass-rate claim here with a band under 30 points.

These are floors to defend, not ceilings to celebrate. The p90 target of 45s was set from an n=18
sample whose tail reached 40s; at n=25 the p90 is 17.2s, so that target is now loose and should be
tightened once another batch confirms it.

## Rules

1. **`found` is the pass rate, never `status`.** A model reporting done proves nothing; the two
   disagree often enough that the disagreement is itself a finding.
2. **State n with every number.** A rate without a denominator is not a measurement.
3. **Quote the interval, not just the point.** "78% (95% CI 52–94, n=18)" is honest; "78%" is not.
4. **Never compare across harness versions.** Runs from before a change measure a different system.
   The 87 runs collected while building this harness are not one sample of anything.
5. **Offline evals are pass/fail, not sampled.** They are deterministic by construction; a flaky
   offline eval is a bug in the eval.

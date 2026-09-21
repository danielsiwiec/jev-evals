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

## Current targets

Measured on `evals/online/test_refinance_e2e.py` with the `jev` driver, current harness (n=18):

| metric | observed | target | n for the claim |
|---|---|---|---|
| pass rate (`found`) | 77.8% [52.4–93.6] | **≥ 75%** | 25 |
| cost per run | $0.0033 | **≤ $0.005** | 10 |
| latency median | 8.4s | **≤ 10s** | 25 |
| latency p90 | 40.3s | **≤ 45s** | 25 |

These are floors to defend, not ceilings to celebrate. They were set from 18 runs, which supports the
cost target and only weakly supports the pass-rate one; the first n=25 batch should replace them.

## Rules

1. **`found` is the pass rate, never `status`.** A model reporting done proves nothing; the two
   disagree often enough that the disagreement is itself a finding.
2. **State n with every number.** A rate without a denominator is not a measurement.
3. **Quote the interval, not just the point.** "78% (95% CI 52–94, n=18)" is honest; "78%" is not.
4. **Never compare across harness versions.** Runs from before a change measure a different system.
   The 87 runs collected while building this harness are not one sample of anything.
5. **Offline evals are pass/fail, not sampled.** They are deterministic by construction; a flaky
   offline eval is a bug in the eval.

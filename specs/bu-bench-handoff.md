# Handoff: running Peregrine against BU Bench

Goal: find out where Peregrine ranks against other browser agents, by running it through
[browser-use/benchmark](https://github.com/browser-use/benchmark) — the one harness where many
frameworks are measured on the same tasks with the same judge.

This is **external** benchmarking. It does not replace `evals/`: those are for diagnosing the harness
and are scored on ground truth. BU Bench is scored by an LLM judge, which is why it lives outside.
Report the two separately and do not let the judge's verdict leak into how `evals/` are scored.

## Start with V1, not V2

V2 is the better-designed benchmark: 200 tasks, and its judge emits findings with evidence while the
score is computed in code from frozen per-task weights, so re-weighting never requires re-judging.
V1 is a plain `verdict: bool`.

Run V1 first anyway, because that is where the comparators are. `official_results/` holds 9 runs and
`old_results/` another 30 — browser-use at several versions, Bcode, Stagehand, Claude CUA — all on
the same 100 tasks. A V1 number is directly comparable today. V2's published results are only "an
earlier 60-task cut". Move to V2 once you want to see *where* points are lost rather than how often.

## What the integration actually is

One function. `frameworks/<name>/` with an `execute` that returns their `ExecutionResult`:

```python
@dataclass
class ExecutionResult:
    final_result: str  # BrowseResult.summary
    steps: list[str]  # BrowseResult.steps
    screenshots_b64: list[str]  # EVAL_TRACE_SHOTS=1 writes these per step
    num_steps: int  # len(result.steps)
    duration_seconds: float  # BrowseResult.duration_s
    cost: float = 0.0  # BrowseResult.cost_usd
```

Peregrine already produces every field. The smallest existing adapter, `frameworks/stagehand`, is 81
lines and most of that is shelling out to Node; ours calls `run_goal` directly and should be shorter.

The entry point is per-task, driven by env vars, not a batch runner:

```
TASK_INDEX=<0..99> BENCHMARK=BU_Bench_V1 python frameworks/peregrine/run.py
```

and inside `main()`: `load_tasks(benchmark)`, `interleave()` when there are 100 tasks, then
`run_and_judge(task, execute)`.

## Facts worth not rediscovering

- **Tasks are encrypted, and the key is derivable** — no secret required:
  `Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"BU_Bench_V1").digest()))` over the base64-decoded
  `.enc` file. Verified: 100 tasks, keys `confirmed_task`, `category`, `task_id`.
- **Do not print or commit task text.** They are encrypted specifically to stay out of crawlers and
  training data, and the repo asks that they not be republished in plaintext.
- **The judge needs `GOOGLE_API_KEY`** and defaults to `gemini-2.5-flash` (`JUDGE_MODEL` overrides).
- Other env vars: `BROWSER`, `TASK_TIMEOUT`, `RUN_DATA_DIR`, `LOCAL_RESULT_FILE`, `NO_INTERLEAVE`.
- A published result is a single summary object: `tasks_completed`, `tasks_successful`, `total_steps`,
  `total_duration`, `total_cost`. The reference point to beat: browser-use v4 with Luna scored
  **78/100** at $6.31 and 4,640 steps.

## Suggested order

1. Write `frameworks/peregrine/run.py`, mapping `run_goal` onto `ExecutionResult`.
2. Run **20 tasks**, not 100. Enough to surface integration bugs cheaply.
3. Compare against the same task indices in `official_results/`.
4. Only then run the full 100.

## Expect a low first score, and treat that as the finding

Peregrine is a single-page harness with a deliberately small action space. BU Bench tasks span
multiple sites, forms and long journeys. There is no `drag`, no way to switch to an arbitrary tab,
and objectives in `evals/` are single-page by design.

The useful output of the first run is not the number. It is which missing capability costs the most
tasks — that is what should drive the next change to the action space, and it belongs back in
`specs/harness-philosophy.md` as a documented gap.

## Caveat

The contract above was read from their source, not run. The "81 lines" and the env var list come from
reading `frameworks/stagehand` and `frameworks/__init__.py`. The 20-task trial is what confirms it.

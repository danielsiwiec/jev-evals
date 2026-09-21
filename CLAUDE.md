# jev-evals

Browser-agent evals comparing three models — `jev`, `gemini`, `luna` — on the same decision loop. See [README.md](README.md) for what they measure and how the pieces fit together.

## Read the specs first

The principles this repo is built on live in [specs/](specs/), not here. They are binding, and several
were written after a bug caused by breaking them:

- **[specs/harness-philosophy.md](specs/harness-philosophy.md)** — the six rules the harness follows:
  decisions belong to jev, jev gets the real unfiltered state, the action space is what a person can
  do, goals state intent only, every run is inspectable, and the harness stays dumb with every
  exception listed. Read this before changing anything under `jev_evals/`.
- **[specs/eval-approach.md](specs/eval-approach.md)** — the offline/online and unit/e2e suites, where
  to iterate, how to capture a failure before fixing it, and how to replicate a real page faithfully.
- **[specs/decisions.md](specs/decisions.md)** — choices that are easy to undo by accident, with the
  evidence behind them. Check here before reversing one.
- **[specs/known-failure-modes.md](specs/known-failure-modes.md)** — what goes wrong and which fixture
  covers it.

Quick orientation, with the detail in the specs:

```bash
make unit                                  # offline fixtures, fast, no keys — iterate here
make unit-online                           # real pages, including fixture validity guards
make e2e                                   # the two full journeys
EVAL=evals/online/test_refinance_e2e.py EVAL_DRIVERS=jev EVAL_RUNS=3 make e2e
```

`make e2e` sources `.env` itself; do not run `uv run pytest` directly for online evals. If `uv` is not
on PATH it lives at `~/.local/bin/uv`. Every run launches its own throwaway Chrome. Set
`EVAL_TRACE_SHOTS=1` for per-step screenshots in `.traces/` when debugging.

## Working on this repo

Run `make check` after changes. Follow the existing style: no comments or docstrings, `_` prefix for module-internal names.

Adding a model that generates JSON decisions is one line in `DRIVERS` in [evals/drivers.py](evals/drivers.py) — anything LiteLLM can reach. A different interface needs a class satisfying the `Decider` protocol in [jev_evals/decider.py](jev_evals/decider.py).

Secrets live in `.env`, which is gitignored. Never commit it or echo key values.

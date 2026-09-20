# jev-evals

Browser-agent evals comparing three models — `jev`, `gemini`, `luna` — on the same decision loop. See [README.md](README.md) for what they measure and how the pieces fit together.

## Running the evals

```bash
make eval                                  # all drivers, both evals
EVAL=evals/test_refinance.py make eval     # one eval
EVAL_DRIVERS=jev,luna EVAL_RUNS=3 make eval
```

`make eval` starts Chrome on CDP 9222 if it isn't already running and sources `.env` itself. Do not run `uv run pytest` directly for evals — nothing in the package auto-loads `.env`, so the keys will be missing and every driver will fail to authenticate.

If `uv` is not on PATH it lives at `~/.local/bin/uv`; the Makefile already resolves this.

## Interpreting results

**A failing assertion is often the correct outcome.** Evals are scored externally — a file on disk, or a lender and rate matched against Bankrate's own API — so a run fails when the agent did not actually achieve the goal. That is a result to report, not a bug to fix. Never loosen a scorer to make a run pass.

Report the per-driver table and say plainly which drivers found the answer. `status` is self-reported by the model; `found` is ground truth. When they disagree, `found` wins and the disagreement is worth mentioning.

A single run on a live commercial site proves little — ad gates, cookie banners and bot protection cause failures unrelated to model quality. Use `EVAL_RUNS=3` or more before drawing conclusions, and read the action traces rather than the status column.

## Known failure modes

- **The form fight.** A model types a value, the page re-renders and discards it, and it types again. Shows up as one element ref repeating with different values while `stuck` climbs. The loop's repeat detector looks for an *unchanged* page, so a page that changes without progressing slips past it.
- **Premature done.** A model claims the goal is met on arrival. External scoring catches this.
- **Download path mismatch.** The download eval watches `DOWNLOADS_DIR`, but Chrome writes to its own profile's download directory. On a fresh profile these differ and every run scores "no file" regardless of model.

## Working on this repo

Run `make check` after changes. Follow the existing style: no comments or docstrings, `_` prefix for module-internal names.

Adding a model that generates JSON decisions is one line in `DRIVERS` in [evals/drivers.py](evals/drivers.py) — anything LiteLLM can reach. A different interface needs a class satisfying the `Decider` protocol in [jev_evals/decider.py](jev_evals/decider.py).

Secrets live in `.env`, which is gitignored. Never commit it or echo key values.

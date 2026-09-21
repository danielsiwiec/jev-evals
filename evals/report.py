from evals.stats import pass_rate, runs_needed, summarise


def render(rows: list[dict], header: str, columns: list[tuple[str, str]]) -> str:
    names = ["run", "driver", "status"] + [c[0] for c in columns]
    keys = ["run", "driver", "status"] + [c[1] for c in columns]
    tail = ["seconds", "model_calls", "model_ms", "input_tokens", "output_tokens"]
    names += ["eff", "seconds", "calls", "mean ms", "in tok", "out tok", "cost USD"]
    keys += ["efficiency"] + tail + ["cost_usd"]
    lines = ["", header, "| " + " | ".join(names) + " |", "|" + "---|" * len(names)]
    for row in rows:
        cells = []
        for key in keys:
            value = row.get(key)
            if isinstance(value, bool):
                value = "yes" if value else "no"
            elif key == "cost_usd" and isinstance(value, (int, float)):
                value = f"{value:.6f}"
            elif key == "efficiency":
                value = f"{value:.0%}" if isinstance(value, float) else "-"
            cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("| driver | found | 95% CI | efficiency | median s | p90 s | mean cost |")
    lines.append("|---|---|---|---|---|---|---|")
    for driver in dict.fromkeys(r["driver"] for r in rows):
        group = [r for r in rows if r["driver"] == driver]
        ok = [r for r in group if r.get("found")]

        def mean(key: str, rs: list[dict]) -> float:
            return (sum(r[key] for r in rs) / len(rs)) if rs else 0.0

        rate = pass_rate(len(ok), len(group))
        timing = summarise([r["seconds"] for r in group])
        scored = [r["efficiency"] for r in group if r.get("efficiency") is not None]
        efficiency = f"{sum(scored) / len(scored) * 100:.0f}%" if scored else "-"
        lines.append(
            f"| {driver} | {len(ok)}/{len(group)} | {rate.low * 100:.0f}-{rate.high * 100:.0f}% "
            f"| {efficiency} | {timing.get('median', 0):.1f} | {timing.get('p90', 0):.1f} "
            f"| {mean('cost_usd', group):.5f} |"
        )
    runs = len(rows) // max(len({r["driver"] for r in rows}), 1)
    if runs < runs_needed(0.20):
        lines.append(
            f"\nn={runs}: a smoke test, not a measurement. Pinning a pass rate to +/-20% needs "
            f"{runs_needed(0.20)} runs, +/-10% needs {runs_needed(0.10)}. See specs/targets.md."
        )
    for row in rows:
        lines.append(f"\nrun {row['run']} {row['driver']} steps:")
        lines.extend(f"  {s}" for s in row.get("steps") or [])
    return "\n".join(lines)

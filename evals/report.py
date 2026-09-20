def render(rows: list[dict], header: str, columns: list[tuple[str, str]]) -> str:
    names = ["run", "driver", "status"] + [c[0] for c in columns]
    keys = ["run", "driver", "status"] + [c[1] for c in columns]
    tail = ["seconds", "model_calls", "model_ms", "input_tokens", "output_tokens"]
    names += ["seconds", "calls", "mean ms", "in tok", "out tok", "cost USD"]
    keys += tail + ["cost_usd"]
    lines = ["", header, "| " + " | ".join(names) + " |", "|" + "---|" * len(names)]
    for row in rows:
        cells = []
        for key in keys:
            value = row.get(key)
            if isinstance(value, bool):
                value = "yes" if value else "no"
            elif key == "cost_usd" and isinstance(value, (int, float)):
                value = f"{value:.6f}"
            cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("| driver | found | mean s | mean cost | mean calls | mean model ms |")
    lines.append("|---|---|---|---|---|---|")
    for driver in dict.fromkeys(r["driver"] for r in rows):
        group = [r for r in rows if r["driver"] == driver]
        ok = [r for r in group if r.get("found")]

        def mean(key: str, rs: list[dict]) -> float:
            return (sum(r[key] for r in rs) / len(rs)) if rs else 0.0

        lines.append(
            f"| {driver} | {len(ok)}/{len(group)} | {mean('seconds', ok):.1f} | {mean('cost_usd', group):.5f} "
            f"| {mean('model_calls', group):.1f} | {mean('model_ms', group):.0f} |"
        )
    for row in rows:
        lines.append(f"\nrun {row['run']} {row['driver']} steps:")
        lines.extend(f"  {s}" for s in row.get("steps") or [])
    return "\n".join(lines)

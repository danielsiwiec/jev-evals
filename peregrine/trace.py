import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

TRACE_DIR = Path(os.getenv("EVAL_TRACE_DIR", ".traces"))
ENABLED = os.getenv("EVAL_TRACE", "1").lower() in ("1", "true", "yes")
SHOTS = os.getenv("EVAL_TRACE_SHOTS", "0").lower() in ("1", "true", "yes")


class Trace:
    def __init__(self, label: str, goal: str):
        self.path: Path | None = None
        if not ENABLED:
            return
        # Parallel runs start within the same second, so a second-resolution stamp alone collides
        # and several runs interleave into one file. A per-run suffix keeps them apart.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:60]
        unique = uuid.uuid4().hex[:6]
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        self.path = TRACE_DIR / f"{stamp}-{safe}-{unique}.jsonl"
        self.shots = TRACE_DIR / f"{stamp}-{safe}-{unique}" if SHOTS else None
        if self.shots is not None:
            self.shots.mkdir(parents=True, exist_ok=True)
        self._write({"kind": "run", "label": label, "goal": goal, "started": stamp})

    def _write(self, record: dict[str, Any]) -> None:
        if self.path is None:
            return
        with self.path.open("a") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    async def shot(self, tab: Any, index: int, when: str) -> str:
        if self.shots is None:
            return ""
        path = self.shots / f"{index:02d}-{when}.png"
        try:
            await tab.screenshot(path)
        except Exception:
            return ""
        return str(path)

    def step(
        self,
        index: int,
        state: dict[str, Any],
        observation: Any,
        decision: Any,
        outcome: str,
        shots: dict[str, str] | None = None,
    ) -> None:
        self._write(
            {
                "kind": "step",
                "step": index,
                "seen_by_jev": state,
                "dom": {
                    "url": observation.url,
                    "title": observation.title,
                    "alerts": observation.alerts,
                    "scroll": observation.scroll,
                    "full_text": observation.full_text,
                    "elements": [e.line() for e in observation.elements],
                },
                "decision": {
                    "action": decision.action,
                    "target": decision.target,
                    "value": decision.value,
                    "key": decision.key,
                    "goal_met": decision.goal_met,
                    "stuck": decision.stuck,
                    "irreversible": decision.irreversible,
                    "action_probabilities": decision.action_probabilities,
                },
                "outcome": outcome,
                "screenshots": shots or {},
            }
        )

    def finish(self, status: str, reason: str) -> None:
        self._write({"kind": "end", "status": status, "reason": reason})

    def efficiency(self, goal: str, labels: list[tuple[str, str]], breakdown: dict[str, int]) -> None:
        """Keep the judge's reasoning, not just its total.

        The per-action verdicts are the diagnostic half of efficiency: the score says how much was
        wasted, and these say which actions it was. Without them a low score is unactionable.
        """
        self._write(
            {
                "kind": "efficiency",
                "goal": goal,
                "breakdown": breakdown,
                "actions": [{"action": action, "label": label} for action, label in labels],
            }
        )

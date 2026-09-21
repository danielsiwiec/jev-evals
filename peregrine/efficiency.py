import os
import re
from dataclasses import dataclass

from typesafe_sdk import Noul

from peregrine.jev import JevClient, JevUsage

# Jev rates a plainly failed action near 0.1 and a plainly useful one near 0.9, but a merely
# aimless one lands around 0.65. A 0.5 cut counts wandering as contribution, so the bar sits above
# the middle of that range.
CONTRIBUTED = float(os.getenv("EVAL_CONTRIBUTED_AT", "0.75"))
_MAX_STEPS = 40
_STEP = re.compile(r"^\s*(\d+)\.\s*(.*)$")


@dataclass(frozen=True)
class Efficiency:
    """What fraction of the actions taken actually moved the run towards its goal.

    Pass rate says whether the goal was reached; efficiency says how much of the work was wasted
    getting there. A run can pass and still be mostly flailing, and that shows up here first.
    """

    contributing: int
    total: int
    verdicts: list[tuple[str, float]]
    cost_usd: float = 0.0

    @property
    def ratio(self) -> float:
        return self.contributing / self.total if self.total else 0.0

    @property
    def wasted(self) -> list[str]:
        return [step for step, score in self.verdicts if score < CONTRIBUTED]

    def __str__(self) -> str:
        return f"{self.ratio:.0%} ({self.contributing}/{self.total} actions contributed)"


def _label(step: str) -> str:
    match = _STEP.match(step)
    return match.group(1) if match else step[:12]


async def judge(goal: str, steps: list[str], jev: JevClient | None = None) -> Efficiency:
    """Ask jev, once, which of these actions contributed.

    Every action is judged against the whole trace rather than in isolation, because contribution is
    only visible in hindsight: opening a filter panel contributes if the filter is then used, and
    does not if the run opens it four times. The trace is the state; one question per action.
    """
    steps = steps[:_MAX_STEPS]
    if not steps:
        return Efficiency(0, 0, [])
    client = jev or JevClient()
    usage = JevUsage()
    state = {
        "goal": goal,
        "actions_taken_in_order": steps,
        "note": ("This run is finished. Judge each action with the benefit of hindsight, against the whole sequence."),
    }
    questions = {
        f"step_{_label(step)}": Noul(
            instructions=(
                f"Did this action move the run towards `goal`: {step!r}? Judge it against the whole "
                "of `actions_taken_in_order`, with hindsight. It contributes if it made progress or "
                "revealed something the run needed. It does not contribute if it repeated an earlier "
                "action to no effect, left the page where the goal could be met, pursued something "
                "the goal never asked for, acted on the wrong element, or failed outright. Once the "
                "goal could already be answered from what was on screen, later actions do not "
                "contribute."
            )
        )
        for step in steps
    }
    answers = await client.ask(state, questions, usage)
    verdicts = [
        (step, float(answers[f"step_{_label(step)}"].noul)) for step in steps if f"step_{_label(step)}" in answers
    ]
    if jev is None:
        await client.close()
    contributing = sum(1 for _, score in verdicts if score >= CONTRIBUTED)
    return Efficiency(contributing, len(verdicts), verdicts, usage.cost_usd)

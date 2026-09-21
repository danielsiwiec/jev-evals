import re
from collections import Counter
from dataclasses import dataclass

from typesafe_sdk import Choice

from peregrine.jev import JevClient, JevUsage

_MAX_STEPS = 40
_STEP = re.compile(r"^\s*(\d+)\.\s*(.*)$")

# What an action was for. A classifier is asked to name it rather than score it: the label is what
# a person needs in order to fix anything, and jev is decisive about labels in a way it is not
# about a 0-1 usefulness score, which sat around 0.75 for both good and aimless actions.
LABELS: dict[str, str] = {
    "progressing": (
        "it moved the run towards the goal: filled a field the goal names, opened or applied a "
        "control the goal needs, or revealed information the goal requires"
    ),
    "redundant": "it repeated something already done, or re-entered a value the field already held",
    "overcontinuing": ("the goal was already answerable from what was on screen, and this went on anyway"),
    "misdirected": "it acted on the wrong thing: a field or control the goal never mentions",
    "exploratory": "it looked around without committing to anything: scrolling or paging",
    "failed": "it did not do what it set out to do",
}
CONTRIBUTING = frozenset({"progressing"})


@dataclass(frozen=True)
class Efficiency:
    """What the run's actions were for, and what fraction of them advanced the goal.

    Pass rate says whether the goal was reached. Efficiency says how much of the work was wasted
    getting there, and the labels say in what way, which is the part worth acting on.
    """

    labels: list[tuple[str, str]]
    cost_usd: float = 0.0

    @property
    def total(self) -> int:
        return len(self.labels)

    @property
    def contributing(self) -> int:
        return sum(1 for _, label in self.labels if label in CONTRIBUTING)

    @property
    def ratio(self) -> float:
        return self.contributing / self.total if self.total else 0.0

    @property
    def breakdown(self) -> dict[str, int]:
        return dict(Counter(label for _, label in self.labels).most_common())

    @property
    def wasted(self) -> list[tuple[str, str]]:
        return [(step, label) for step, label in self.labels if label not in CONTRIBUTING]

    def __str__(self) -> str:
        parts = ", ".join(f"{n} {name}" for name, n in self.breakdown.items())
        return f"{self.ratio:.0%} ({self.contributing}/{self.total} progressing; {parts})"


def _key(step: str) -> str:
    match = _STEP.match(step)
    return match.group(1) if match else step[:12]


async def judge(
    goal: str,
    steps: list[str],
    jev: JevClient | None = None,
    reached_at: int = 0,
    values: dict[str, str] | None = None,
    answer_visible_from: int = 0,
) -> Efficiency:
    """Ask jev, in one call, what each action was for.

    Every action is judged against the whole trace rather than in isolation, because what an action
    was for is only visible in hindsight: paging contributes if the run then acts on what it found,
    and is redundant if it pages again instead.
    """
    steps = steps[:_MAX_STEPS]
    if not steps:
        return Efficiency([])
    client = jev or JevClient()
    usage = JevUsage()
    state: dict[str, object] = {
        "goal": goal,
        "actions_taken_in_order": steps,
        "note": (
            "This run is finished. An action being carried out does not make it useful: the report "
            "says what the browser did, not whether it was the right thing to do. Judge what each "
            "action was for, with hindsight, against the whole sequence."
        ),
    }
    if values:
        state["values_the_goal_supplies"] = values
    if reached_at:
        state["the_run_came_closest_to_believing_it_was_finished_at_step"] = reached_at
    if answer_visible_from:
        # Ground truth from the eval, not the run's own opinion: after this step the goal could have
        # been answered from what was on screen, so later actions are overcontinuing unless they
        # were needed to report it.
        state["the_answer_was_on_screen_from_step"] = answer_visible_from
    questions = {
        f"step_{_key(step)}": Choice(
            instructions=f"What was this action for, judged against `goal`: {step!r}?",
            criteria=dict(LABELS),
        )
        for step in steps
    }
    answers = await client.ask(state, questions, usage)
    labels = [(step, str(answers[f"step_{_key(step)}"].choice)) for step in steps if f"step_{_key(step)}" in answers]
    if jev is None:
        await client.close()
    return Efficiency(labels, usage.cost_usd)

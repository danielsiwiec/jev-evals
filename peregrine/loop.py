import os
import time
from collections.abc import Awaitable, Callable

from loguru import logger
from pydantic import BaseModel
from typesafe_sdk import Noul

from peregrine.actions import (
    TARGET_ACTIONS,
    VALUE_ACTIONS,
    Decision,
    Observation,
    build_state,
    visible_elements,
)
from peregrine.decider import Decider, JevDecider
from peregrine.jev import JevClient, JevUsage
from peregrine.page import Tab
from peregrine.telemetry import start_span
from peregrine.text_helper import TextHelper, TextUnavailable, field_context
from peregrine.trace import Trace

MAX_STEPS = int(os.getenv("BROWSER_MAX_STEPS", "20"))
TIMEOUT_S = float(os.getenv("BROWSER_TIMEOUT_S", "120"))
MAX_CANDIDATES = int(os.getenv("BROWSER_MAX_CANDIDATES", "80"))
_DONE_AGREEMENT = 0.5
_STUCK = 0.8
_REPEAT_LIMIT = 4
_WINDOW = 8
_WAIT_S = 2.0
_WAIT_MAX_S = 10.0
_SUMMARY_CHARS = 40000

OnStep = Callable[[int, str], Awaitable[None]]


class BrowseResult(BaseModel):
    status: str
    url: str = ""
    title: str = ""
    summary: str = ""
    reason: str = ""
    steps: list[str] = []
    decider: str = ""
    jev_calls: int = 0
    jev_tokens: int = 0
    output_tokens: int = 0
    jev_mean_ms: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    trace_path: str = ""
    text_model: str = ""
    text_calls: int = 0
    text_mean_ms: int = 0

    def render(self) -> str:
        lines = [f"status: {self.status}"]
        if self.reason:
            lines.append(f"reason: {self.reason}")
        lines += [f"url: {self.url}", f"title: {self.title}"]
        if self.steps:
            lines.append("steps:\n  " + "\n  ".join(self.steps))
        lines.append(f"page text: {self.summary}")
        lines.append(
            f"({len(self.steps)} steps, {self.jev_calls} {self.decider or 'jev'} calls averaging {self.jev_mean_ms}ms, "
            f"${self.cost_usd:.5f}, {self.duration_s:.1f}s)"
        )
        return "\n".join(lines)


async def run_goal(
    tab: Tab,
    jev: JevClient | Decider,
    goal: str,
    values: dict[str, str] | None = None,
    max_steps: int = MAX_STEPS,
    timeout_s: float = TIMEOUT_S,
    on_step: OnStep | None = None,
) -> BrowseResult:
    values = {k: str(v) for k, v in (values or {}).items() if str(v)}
    decider: Decider = JevDecider(jev) if isinstance(jev, JevClient) else jev
    usage = JevUsage()
    started = time.perf_counter()
    history: list[str] = []
    fingerprints: list[str] = []
    targets: list[str] = []
    waits = 0
    view_page = 0
    observation: Observation | None = None
    status, reason = "max_steps", f"stopped after {max_steps} steps"

    helper = TextHelper()
    trace = Trace(getattr(decider, "model", "jev"), goal)
    with start_span("browser_run") as span:
        span.set_attribute("browser.goal", goal[:200])
        for step in range(1, max_steps + 1):
            if time.perf_counter() - started > timeout_s:
                status, reason = "timeout", f"exceeded {timeout_s:.0f}s"
                break
            observation = await tab.observe()
            fingerprints.append(observation.fingerprint())
            state = build_state(
                goal,
                values,
                observation,
                observation.elements,
                history,
                text_chars=getattr(decider, "max_text_chars", None),
                page=view_page,
                tabs=await tab.tabs(),
            )
            candidates = visible_elements(observation, goal, view_page)
            decision = await decider.decide(state, values, candidates, usage)
            if decision.action == "done" and decision.goal_met < _DONE_AGREEMENT:
                decision = decision.without("done")
            logger.info(f"🧭 step {step}: {decision.render()}")

            if decision.action == "done":
                status, reason = "done", f"goal met (p={decision.goal_met:.2f})"
                break
            if decision.action == "blocked":
                status, reason = "blocked", _blocked_reason(observation, history)
                break
            if decision.stuck >= _STUCK or _no_progress(fingerprints, targets):
                status, reason = "stuck", "page stopped changing"
                break

            if decision.action == "show_more":
                more = (state.get("not_shown") or {}).copy()
                more.pop("how_to_see_it", None)
                if not more:
                    entry = f"{step}. show_more -> nothing further is being held back"
                    view_page = 0
                else:
                    view_page += 1
                    entry = f"{step}. show_more -> showing the next part of {', '.join(sorted(more))}"
                history.append(entry)
                # Paging counts as a step like any other, so a run that only ever asks for more
                # is caught by the no-progress guard instead of paging until it runs out of steps.
                targets.append("show_more")
                trace.step(step, state, observation, decision, entry.split("-> ", 1)[1])
                if on_step is not None:
                    await on_step(step, entry)
                continue
            view_page = 0
            waits = waits + 1 if decision.action == "wait" else 0
            before_shot = await trace.shot(tab, step, "before")
            outcome = await _perform(tab, decision, observation, values, waits, helper, goal, history)
            targets.append(f"{decision.action}:{decision.target}")
            if outcome != "download started" and (await tab.observe()).fingerprint() == fingerprints[-1]:
                outcome += " (page unchanged)"
            entry = f"{step}. {_pending(decision, observation, values)} -> {outcome}"
            history.append(entry)
            trace.step(
                step,
                state,
                observation,
                decision,
                outcome,
                {"before": before_shot, "after": await trace.shot(tab, step, "after")},
            )
            if on_step is not None:
                await on_step(step, entry)
            if outcome == "download started":
                status, reason = "done", "a file download was started"
                break
        else:
            observation = await tab.observe()

        if observation is None or observation.url != (tab.page.url if tab.page else observation.url):
            observation = await tab.observe()
        span.set_attribute("browser.status", status)
        span.set_attribute("browser.steps", len(history))
        span.set_attribute("gen_ai.usage.cost_usd", usage.cost_usd)
        trace.finish(status, reason)

    return BrowseResult(
        trace_path=str(trace.path) if trace.path else "",
        status=status,
        url=observation.url,
        title=observation.title,
        summary=(observation.full_text or observation.text)[:_SUMMARY_CHARS],
        reason=reason,
        steps=history,
        decider=decider.model,
        jev_calls=usage.calls,
        jev_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        jev_mean_ms=usage.mean_ms,
        cost_usd=round(usage.cost_usd + helper.cost_usd, 8),
        text_model=helper.model if helper.calls else "",
        text_calls=helper.calls,
        text_mean_ms=helper.mean_ms,
        duration_s=round(time.perf_counter() - started, 2),
    )


async def check(tab: Tab, jev: JevClient, question: str) -> tuple[float, JevUsage]:
    usage = JevUsage()
    observation = await tab.observe()
    state = {
        "page": {
            "url": observation.url,
            "title": observation.title,
            "alerts": observation.alerts,
            "text": observation.text,
        }
    }
    answers = await jev.ask(state, {"answer": Noul(instructions=question)}, usage)
    return float(answers["answer"].noul), usage


def _blocked_reason(observation: Observation, history: list[str]) -> str:
    dialog = next(
        (h.split("dialog dismissed: ", 1)[1].rstrip(")") for h in reversed(history) if "dialog dismissed: " in h), ""
    )
    if dialog:
        return f"the page said: {dialog}"
    if observation.alerts:
        return "the page shows: " + " | ".join(observation.alerts)[:200]
    return "no way forward from this page (login wall, error, or missing content)"


def _no_progress(fingerprints: list[str], targets: list[str]) -> bool:
    """One question: have the last few steps changed anything?

    Two ways to answer it. The page stopped changing at all, or the same action and target keep
    being retried within a short window — which a changing page would otherwise hide.
    """
    recent = [t for t in targets[-_WINDOW:] if not t.startswith("wait")]
    if any(recent.count(t) >= _REPEAT_LIMIT for t in set(recent)):
        return True
    return len(fingerprints) > _REPEAT_LIMIT and len(set(fingerprints[-_REPEAT_LIMIT - 1 :])) == 1


def _pending(decision: Decision, observation: Observation, values: dict[str, str] | None = None) -> str:
    target = observation.find(decision.target) if decision.target is not None else None
    text = decision.action
    if decision.action in TARGET_ACTIONS and target is not None:
        text += f" {target.line()}"
    if decision.action in VALUE_ACTIONS and decision.value:
        shown = (values or {}).get(decision.value)
        text += f" with {decision.value}='{shown}'" if shown else f" with value '{decision.value}'"
    return text


async def _perform(
    tab: Tab,
    decision: Decision,
    observation: Observation,
    values: dict[str, str],
    waits: int = 0,
    helper: TextHelper | None = None,
    goal: str = "",
    history: list[str] | None = None,
) -> str:
    action = decision.action
    if action in TARGET_ACTIONS:
        if decision.target is None:
            return f"{action} needs a target element and none was chosen"
        if observation.find(decision.target) is None:
            return f"#{decision.target} is not an element on this page"
        if action == "click":
            return await tab.click(decision.target)
        if action == "press":
            return await tab.press(decision.key or "Enter", decision.target)
        if action == "compose":
            if helper is None or not helper.available:
                return "composing text needs a text model; none is configured"
            target = observation.find(decision.target)
            field = target.describe() if target else str(decision.target)
            try:
                composed = await helper.value_for(field_context(goal, field, observation, history or []))
            except TextUnavailable as error:
                return f"no text could be composed: {error}"
            return await tab.type(decision.target, composed, submit=True) + f" (composed {composed!r})"
        if action in VALUE_ACTIONS:
            # A prepared value wins when one was chosen; otherwise the model's own text is used.
            if decision.value in values:
                value = values[decision.value]
            elif decision.text:
                value = decision.text
            else:
                known = ", ".join(sorted(values)) or "none"
                return f"no text was chosen to type; available prepared values are: {known}"
        if action in ("type", "submit"):
            return await tab.type(decision.target, value, submit=action == "submit")
        return await tab.select(decision.target, value)
    if action == "scroll_down":
        return await tab.scroll(1)
    if action == "scroll_up":
        return await tab.scroll(-1)
    if action == "back":
        return await tab.back()
    if action == "refresh":
        return await tab.refresh()
    if action == "close_tab":
        return await tab.close_tab()
    if action == "press":
        return await tab.press(decision.key or "Enter")
    if action == "wait":
        return await tab.sleep(min(_WAIT_S * (2 ** max(waits - 1, 0)), _WAIT_MAX_S))
    return f"unsupported action {action}"

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from typesafe_sdk import Choice, Noul

ACTIONS: dict[str, str] = {
    "click": "click the target element (a link, button, checkbox, menu item, or an option)",
    "type": "type one of the available values into the target text field or search box",
    "submit": "type one of the available values into the target field and press Enter to submit it",
    "select": "choose one of the available values in the target dropdown",
    "scroll_down": "scroll down because what is needed is probably further down the page",
    "scroll_up": "scroll up because what is needed is probably above",
    "back": "go back to the previous page because this page is a dead end",
    "close_tab": "close this tab and return to the one it was opened from",
    "press": "press a single key such as Enter, Escape or Tab, on the target element if one is given",
    "refresh": "reload the current page",
    "show_more": "reveal the part of this page's elements, text or earlier actions that is being held back",
    "wait": "wait because the page is still loading or a challenge is clearing",
    "done": "the goal is already fully achieved on this page; nothing else to do",
    "blocked": "the goal cannot be achieved from here: login wall, captcha, error, or the content does not exist",
}
VALUE_ACTIONS = frozenset({"type", "submit", "select"})
TARGET_ACTIONS = frozenset({"click", "type", "submit", "select"})
TYPEABLE_KINDS = frozenset({"textbox", "search", "email", "number", "password", "url", "tel", "date", "combobox"})
TARGET_QUESTION = {
    "click": "click_target",
    "type": "type_target",
    "submit": "type_target",
    "select": "select_target",
    "press": "press_target",
}
KEYS = ("Enter", "Escape", "Tab", "ArrowDown", "ArrowUp")
CRITERIA_STYLES = ("full", "names", "refs")
_SECRET = re.compile(r"pass|secret|token|key|pin|cvv|ssn", re.I)
_VALUE_LEN = 120
_TEXT_EXCERPT = 1800
_TEXT_PAGE = 1800
_ELEMENT_PAGE = 80
_HISTORY_PAGE = 10
_NAME_LEN = 80
_HISTORY_WINDOW = 10
_VALUE_FOR = "value_for_"


@dataclass(frozen=True)
class Element:
    ref: int
    kind: str
    name: str
    extra: str = ""
    in_viewport: bool = True
    modal: bool = False

    @property
    def typeable(self) -> bool:
        return self.kind in TYPEABLE_KINDS

    @property
    def selectable(self) -> bool:
        return self.kind == "select"

    @property
    def clickable(self) -> bool:
        return not self.typeable

    def describe(self) -> str:
        parts = [self.kind, f"'{self.name}'" if self.name else "''"]
        if self.extra:
            parts.append(self.extra)
        if self.modal:
            parts.append("[in dialog]")
        if not self.in_viewport:
            parts.append("[offscreen]")
        return " ".join(parts)

    def line(self) -> str:
        return f"#{self.ref} {self.describe()}"


@dataclass
class Observation:
    url: str
    title: str
    text: str
    alerts: list[str]
    scroll: dict[str, int]
    elements: list[Element]
    raw: dict[str, Any] = field(default_factory=dict)
    full_text: str = ""

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Observation":
        elements = [
            Element(
                ref=int(e["ref"]),
                kind=str(e.get("kind", "")),
                name=_clean(str(e.get("name", "")))[:_NAME_LEN],
                extra=_clean(str(e.get("extra", "")))[:_NAME_LEN],
                in_viewport=bool(e.get("inViewport", True)),
                modal=bool(e.get("modal", False)),
            )
            for e in raw.get("elements", [])
        ]
        full_text = _clean_text(str(raw.get("text", "")))
        return cls(
            url=str(raw.get("url", "")),
            title=_clean(str(raw.get("title", ""))),
            text=full_text[:_TEXT_EXCERPT],
            alerts=[_clean(a)[:200] for a in raw.get("alerts", []) if _clean(a)],
            scroll=dict(raw.get("scroll", {})),
            elements=elements,
            raw=raw,
            full_text=full_text,
        )

    def fingerprint(self) -> str:
        body = self.url + self.title + self.text[:600] + "|".join(e.line() for e in self.elements[:60])
        return hashlib.sha1(body.encode()).hexdigest()

    def find(self, ref: int) -> Element | None:
        return next((e for e in self.elements if e.ref == ref), None)

    def render(self, max_elements: int = 120) -> str:
        lines = [f"url: {self.url}", f"title: {self.title}"]
        if self.alerts:
            lines.append("alerts: " + " | ".join(self.alerts))
        if self.scroll:
            position = f"{self.scroll.get('y', 0)}/{self.scroll.get('height', 0)}"
            lines.append(f"scroll: {position} (viewport {self.scroll.get('viewport', 0)})")
        lines.append(f"text:\n{self.text}")
        shown = min(len(self.elements), max_elements)
        lines.append(f"elements ({len(self.elements)} interactive, showing {shown}):")
        lines.extend(e.line() for e in self.elements[:max_elements])
        return "\n".join(lines)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_text(text: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _masked(name: str, value: str) -> str:
    return "(hidden)" if _SECRET.search(name) else value[:_VALUE_LEN]


def ranked_elements(elements: list[Element], goal: str) -> list[Element]:
    """What is physically in the way first: a blocking dialog, then what is on screen.

    Both terms are facts about the page, not guesses about relevance. A modal blocks every other
    control until it is dealt with, so it has to be reachable on the first page however large the
    page is. Deciding which elements *matter* is jev's job; pagination walks this order and
    `show_more` reveals the rest.
    """

    def score(e: Element) -> tuple[int, int]:
        return (1 if e.modal else 0, 1 if e.in_viewport else 0)

    return sorted(elements, key=score, reverse=True)


def _page_of(items: list[Any], page: int, size: int) -> tuple[list[Any], int]:
    start = page * size
    return items[start : start + size], max(len(items) - start - size, 0)


_PHRASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,'&/-]{2,59}")
_STOP = {"the", "and", "for", "with", "from", "that", "this", "report", "find", "out", "when"}


def goal_phrases(goal: str, limit: int = 12) -> list[str]:
    """Substrings of the goal that could plausibly be typed into a field.

    jev answers Choice/Noul/Score and cannot generate text, so free typing is offered to it as a
    selection among phrases the goal already contains. Quoted spans come first because a task that
    quotes a string usually means it literally. Generative deciders ignore this and use `text`.
    """
    quoted = re.findall(r'"([^"]{2,60})"|\u201c([^\u201d]{2,60})\u201d', goal)
    phrases = [a or b for a, b in quoted]
    words = [w for w in re.findall(r"[A-Za-z0-9'&.-]+", goal) if w.lower() not in _STOP]
    for size in (4, 3, 2):
        for i in range(len(words) - size + 1):
            phrases.append(" ".join(words[i : i + size]))
    seen: dict[str, None] = {}
    for phrase in phrases:
        cleaned = phrase.strip(" .,")
        if len(cleaned) >= 3:
            seen.setdefault(cleaned, None)
    return list(seen)[:limit]


def visible_elements(observation: "Observation", goal: str, page: int = 0) -> list["Element"]:
    shown, _ = _page_of(ranked_elements(observation.elements, goal), page, _ELEMENT_PAGE)
    return sorted(shown, key=lambda e: e.ref)


def build_state(
    goal: str,
    values: dict[str, str],
    observation: Observation,
    elements: list[Element],
    history: list[str],
    text_chars: int | None = None,
    page: int = 0,
    tabs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Nothing is silently withheld: whatever is not shown is counted, and `show_more` reveals it."""
    size = text_chars or _TEXT_PAGE
    text, text_left = _page_of(list(observation.full_text or observation.text), page, size)
    text = "".join(text)
    shown_elements, elements_left = _page_of(ranked_elements(elements, goal), page, _ELEMENT_PAGE)
    shown_elements = sorted(shown_elements, key=lambda e: e.ref)
    shown_history, history_left = _page_of(list(reversed(history)), page, _HISTORY_PAGE)
    page_text = text.lower()
    state: dict[str, Any] = {
        "goal": goal,
        "available_values": {name: _masked(name, value) for name, value in sorted(values.items())},
        "values_now_visible_in_page_text": sorted(name for name, value in values.items() if value.lower() in page_text),
        "page": {
            "url": observation.url,
            "title": observation.title,
            "alerts": observation.alerts,
            "scroll": observation.scroll,
            "text": text,
        },
        "elements": [e.line() for e in shown_elements],
        "recent_actions": list(reversed(shown_history)),
    }
    if tabs and len(tabs) > 1:
        state["open_tabs"] = tabs
    withheld = {
        "page_text_characters": text_left,
        "elements": elements_left,
        "earlier_actions": history_left,
    }
    if any(withheld.values()):
        state["not_shown"] = {k: v for k, v in withheld.items() if v}
        state["not_shown"]["how_to_see_it"] = "choose show_more"
    return state


def _criterion(element: Element, style: str) -> Any:
    if style == "refs":
        return None
    if style == "names":
        return element.name or element.kind
    return element.describe()


def build_questions(
    values: dict[str, str], elements: list[Element], style: str | None = None, goal: str = ""
) -> dict[str, Any]:
    style = style or os.getenv("BROWSER_JEV_CRITERIA", "refs")
    if style not in CRITERIA_STYLES:
        style = "full"
    hint = " Each option is the element's #ref number as listed in `elements`." if style != "full" else ""
    questions: dict[str, Any] = {
        "action": Choice(
            instructions=(
                "Which single next browser action best advances `goal` on this `page`, "
                "given `elements` and `recent_actions`?"
            ),
            criteria=dict(ACTIONS),
        ),
        "goal_met": Noul(
            instructions=(
                "Considering `recent_actions` already performed and the current `page.text`, is `goal` "
                "now fully achieved (the requested content is visible, or the requested state is reached, "
                "for example an entry listed in `values_now_visible_in_page_text` was entered as the goal wanted)?"
            )
        ),
        "stuck": Noul(
            instructions=(
                "Do `recent_actions` show the same action repeating without the `page` changing, "
                "so that no available action makes progress?"
            )
        ),
        "irreversible": Noul(
            instructions=(
                "Would the next action submit a payment, send a message, delete something, "
                "or otherwise cause an effect that cannot be undone?"
            )
        ),
    }
    groups = {
        "click_target": ("clicked", [e for e in elements if e.clickable]),
        "type_target": ("typed into", [e for e in elements if e.typeable]),
        "select_target": ("used to choose an option", [e for e in elements if e.selectable]),
        "press_target": ("the target of a keystroke", list(elements)),
    }
    for name, (verb, group) in groups.items():
        if group:
            questions[name] = Choice(
                instructions=(
                    f"Which element in `elements` should be {verb} next to advance `goal`? "
                    "Prefer elements in a dialog if one blocks the page." + hint
                ),
                criteria={str(e.ref): _criterion(e, style) for e in group},
            )
    questions["key"] = Choice(
        instructions="If a single key is to be pressed, which one?",
        criteria=dict.fromkeys(KEYS),
    )
    typeable = [e for e in elements if e.typeable]
    if typeable:
        phrases = goal_phrases(goal)
        if phrases:
            questions["text_to_type"] = Choice(
                instructions=(
                    "If text must be typed and none of `available_values` fits, which of these phrases "
                    "from the goal should be typed into the chosen field? Pick the one a person would "
                    "enter to make progress, for example the terms they would put in a search box."
                ),
                criteria=dict.fromkeys(phrases),
            )
    if values:
        questions["value"] = Choice(
            instructions=(
                "If text must be typed or an option chosen, which of `available_values` belongs in the field "
                "chosen as `type_target` or `select_target`? Match the value to that field's own label, not to "
                "the goal as a whole: a field labelled for one quantity must not receive another quantity's value."
            ),
            criteria=dict.fromkeys(values),
        )
        for element in elements:
            if element.typeable or element.selectable:
                questions[f"{_VALUE_FOR}{element.ref}"] = Choice(
                    instructions=(
                        f"The field labelled '{element.name or element.kind}' is about to be filled. "
                        "Which of `available_values` is the value for that field? Judge by the field's own "
                        "label alone, ignoring which value the goal mentions first."
                    ),
                    criteria=dict.fromkeys(values),
                )
    return questions


@dataclass(frozen=True)
class Decision:
    action: str
    target: int | None
    value: str | None
    action_confidence: float
    target_confidence: float
    goal_met: float
    stuck: float
    irreversible: float
    action_probabilities: dict[str, float] = field(default_factory=dict)
    targets: dict[str, tuple[int, float]] = field(default_factory=dict)
    text: str | None = None
    key: str | None = None

    def without(self, *actions: str) -> "Decision":
        remaining = {k: v for k, v in self.action_probabilities.items() if k not in actions}
        if not remaining:
            return self
        best = max(remaining, key=lambda name: remaining[name])
        target, confidence = self.targets.get(best, (None, 0.0))
        return Decision(
            best,
            target,
            self.value,
            remaining[best],
            confidence,
            self.goal_met,
            self.stuck,
            self.irreversible,
            remaining,
            self.targets,
            self.text,
            self.key,
        )

    def render(self) -> str:
        bits = [self.action]
        if self.target is not None:
            bits.append(f"#{self.target}")
        if self.value:
            bits.append(f"value={self.value}")
        return " ".join(bits) + f" (goal_met={self.goal_met:.2f} stuck={self.stuck:.2f})"


def parse_decision(answers: dict[str, Any]) -> Decision:
    action = answers["action"]
    value = answers.get("value")
    key = answers.get("key")
    typed = answers.get("text_to_type")
    targets: dict[str, tuple[int, float]] = {}
    for name, question in TARGET_QUESTION.items():
        answer = answers.get(question)
        if answer is not None:
            targets[name] = (int(answer.choice), float(getattr(answer, "confidence", 0.0) or 0.0))
    chosen = str(action.choice)
    target, confidence = targets.get(chosen, (None, 0.0))
    if chosen in VALUE_ACTIONS and target is not None:
        per_field = answers.get(f"{_VALUE_FOR}{target}")
        if per_field is not None:
            value = per_field
    return Decision(
        action=chosen,
        key=str(key.choice) if key is not None else None,
        text=str(typed.choice) if typed is not None else None,
        target=target,
        value=str(value.choice) if value is not None else None,
        action_confidence=float(getattr(action, "confidence", 0.0) or 0.0),
        target_confidence=confidence,
        goal_met=float(answers["goal_met"].noul),
        stuck=float(answers["stuck"].noul),
        irreversible=float(answers["irreversible"].noul),
        action_probabilities={str(k): float(v) for k, v in (getattr(action, "probabilities", None) or {}).items()},
        targets=targets,
    )


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)

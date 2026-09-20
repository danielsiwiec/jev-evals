from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class _Span:
    def set_attribute(self, key: str, value: Any) -> None:
        return None


@contextmanager
def start_span(name: str) -> Iterator[_Span]:
    yield _Span()


def record_call_cost(model: str, cost: float) -> None:
    return None

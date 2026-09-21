import math
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    passed: int
    total: int
    low: float
    high: float

    def __str__(self) -> str:
        pct = self.passed / self.total * 100 if self.total else 0.0
        band = f"{self.low * 100:.1f}-{self.high * 100:.1f}"
        return f"{self.passed}/{self.total} = {pct:.1f}% (95% CI {band}, n={self.total})"


def pass_rate(passed: int, total: int) -> Rate:
    """Clopper-Pearson interval: exact, and does not pretend a small sample is normal."""
    if total == 0:
        return Rate(0, 0, 0.0, 1.0)
    low = 0.0 if passed == 0 else _beta_ppf(0.025, passed, total - passed + 1)
    high = 1.0 if passed == total else _beta_ppf(0.975, passed + 1, total - passed)
    return Rate(passed, total, low, high)


def runs_needed(margin: float, rate: float = 0.5, confidence: float = 0.95) -> int:
    """How many runs to pin a pass rate to +/- margin. Leave rate at 0.5 when it is unknown."""
    z = _z(confidence)
    return math.ceil(z * z * rate * (1 - rate) / (margin * margin))


def runs_needed_for_mean(values: list[float], relative_margin: float, confidence: float = 0.95) -> int:
    """How many runs to pin a mean to +/- a fraction of itself, from the spread already seen."""
    if len(values) < 2:
        return 0
    mean = statistics.mean(values)
    if mean == 0:
        return 0
    cv = statistics.stdev(values) / mean
    return math.ceil((_z(confidence) * cv / relative_margin) ** 2)


def summarise(values: list[float]) -> dict[str, float]:
    """Median and p90, because a skewed distribution's mean describes no actual run."""
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "median": statistics.median(ordered),
        "p90": ordered[min(int(len(ordered) * 0.9), len(ordered) - 1)],
        "mean": statistics.mean(ordered),
        "cv": statistics.stdev(ordered) / statistics.mean(ordered) if len(ordered) > 1 else 0.0,
    }


def _z(confidence: float) -> float:
    return {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence, 1.96)


def _beta_ppf(q: float, a: float, b: float) -> float:
    low, high = 0.0, 1.0
    for _ in range(200):
        mid = (low + high) / 2
        if _beta_cdf(mid, a, b) < q:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _beta_cdf(x: float, a: float, b: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    f, c, d = 1.0, 1.0, 0.0
    for i in range(300):
        m = i // 2
        if i == 0:
            numerator = 1.0
        elif i % 2 == 0:
            numerator = (m * (b - m) * x) / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            numerator = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + numerator * d
        d = 1e-30 if abs(d) < 1e-30 else d
        c = 1.0 + numerator / c
        c = 1e-30 if abs(c) < 1e-30 else c
        d = 1.0 / d
        delta = c * d
        f *= delta
        if abs(1.0 - delta) < 1e-12:
            break
    return front * (f - 1) / a

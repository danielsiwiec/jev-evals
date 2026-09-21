from evals.stats import pass_rate, runs_needed, runs_needed_for_mean, summarise


def test_interval_matches_exact_clopper_pearson():
    # Verified against scipy.stats.beta.ppf: 14/18 -> [52.4%, 93.6%]
    rate = pass_rate(14, 18)
    assert abs(rate.low - 0.524) < 0.002, rate.low
    assert abs(rate.high - 0.936) < 0.002, rate.high


def test_a_perfect_small_batch_is_still_uncertain():
    """The point of the whole exercise: 4/4 does not mean 100%."""
    rate = pass_rate(4, 4)
    assert rate.high == 1.0
    assert rate.low < 0.45, f"4/4 should admit rates below 45%, got {rate.low:.2f}"


def test_a_failed_small_batch_is_also_uncertain():
    rate = pass_rate(0, 4)
    assert rate.low == 0.0
    assert rate.high > 0.55, f"0/4 should admit rates above 55%, got {rate.high:.2f}"


def test_more_runs_narrow_the_interval():
    small = pass_rate(8, 10)
    large = pass_rate(80, 100)
    assert (large.high - large.low) < (small.high - small.low) / 2


def test_runs_needed_is_worst_case_at_an_unknown_rate():
    assert runs_needed(0.20) == 25
    assert runs_needed(0.10) == 97
    assert runs_needed(0.10, rate=0.78) < runs_needed(0.10)


def test_runs_needed_for_mean_scales_with_spread():
    steady = [10.0, 10.5, 9.5, 10.2, 9.8]
    spiky = [5.0, 40.0, 6.0, 45.0, 7.0]
    assert runs_needed_for_mean(spiky, 0.20) > runs_needed_for_mean(steady, 0.20)


def test_summarise_reports_median_and_tail_separately():
    values = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 90.0]
    stats = summarise(values)
    assert stats["median"] < stats["mean"], "a skewed sample must show mean above median"
    assert stats["p90"] >= 13.0
    assert stats["cv"] > 1.0

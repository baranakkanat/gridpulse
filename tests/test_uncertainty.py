import numpy as np
import pandas as pd
import pytest

from gridpulse.uncertainty import block_bootstrap_mean, rolling_conformal_halfwidths


def residual_rows(errors: dict[int, list[float]], start: str = "2018-01-01") -> pd.DataFrame:
    """Rows of (origin, lead, abs_error) from per-lead daily error lists."""
    frames = []
    for lead, values in errors.items():
        origins = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
        frames.append(
            pd.DataFrame({"forecast_origin_utc": origins, "lead_hours": lead, "abs_error": values})
        )
    return pd.concat(frames, ignore_index=True)


def halfwidths_of(result: pd.DataFrame, lead: int) -> list[float]:
    return result.loc[result["lead_hours"] == lead, "halfwidth_mw"].tolist()


def test_halfwidth_uses_only_strictly_earlier_days_and_the_conformal_rank():
    # window 3 days, alpha 0.5: rank = ceil((n + 1) * 0.5) of the sorted window
    result = rolling_conformal_halfwidths(
        residual_rows({1: [1.0, 5.0, 3.0, 100.0, 7.0]}), window_days=3, alpha=0.5
    )
    assert halfwidths_of(result, 1) == [np.inf, 1.0, 5.0, 3.0, 5.0]
    # Day 3 uses days 0-2 (1, 5, 3): its own residual of 100 never enters its interval.
    assert result["n_calibration"].tolist() == [0, 1, 2, 3, 3]


def test_unavailable_residuals_shrink_the_window_and_leads_are_separate():
    result = rolling_conformal_halfwidths(
        residual_rows({1: [2.0, np.nan, 4.0, 1.0], 2: [10.0, 20.0, 30.0, 40.0]}),
        window_days=3,
        alpha=0.5,
    )
    assert result.loc[result["lead_hours"] == 1, "n_calibration"].tolist() == [0, 1, 1, 2]
    assert halfwidths_of(result, 1) == [np.inf, 2.0, 2.0, 4.0]
    assert halfwidths_of(result, 2) == [np.inf, 10.0, 20.0, 20.0]


def test_rank_beyond_the_window_gives_an_uninformative_interval():
    # alpha 0.1 with 3 residuals: rank ceil(4 * 0.9) = 4 > 3
    result = rolling_conformal_halfwidths(
        residual_rows({1: [1.0, 2.0, 3.0, 4.0]}), window_days=3, alpha=0.1
    )
    assert np.isinf(halfwidths_of(result, 1)[3])


def test_coverage_is_close_to_nominal_for_independent_errors():
    """Implementation check: with exchangeable errors the rolling interval covers ~90 %."""
    rng = np.random.default_rng(0)
    days, leads = 1500, 24
    errors = {lead: np.abs(rng.normal(0, 1 + lead / 10, days)).tolist() for lead in range(1, 25)}
    rows = residual_rows(errors)
    result = rows.merge(rolling_conformal_halfwidths(rows, window_days=56, alpha=0.1))
    used = result[result["n_calibration"] == 56]
    coverage = (used["abs_error"] <= used["halfwidth_mw"]).mean()

    assert len(used) == (days - 56) * leads
    # Expected about 52 / 57 = 0.912 for an exact finite-sample rank.
    assert 0.90 < coverage < 0.925


def test_duplicate_or_off_grid_origins_are_rejected():
    rows = residual_rows({1: [1.0, 2.0]})
    with pytest.raises(ValueError, match="duplicate"):
        rolling_conformal_halfwidths(pd.concat([rows, rows]))
    shifted = rows.assign(forecast_origin_utc=rows["forecast_origin_utc"] + pd.Timedelta(hours=1))
    with pytest.raises(ValueError, match="daily grid"):
        rolling_conformal_halfwidths(pd.concat([rows, shifted.iloc[[0]]]))


def test_block_bootstrap_is_deterministic_and_brackets_the_mean():
    values = np.random.default_rng(1).normal(5.0, 2.0, 200)
    first = block_bootstrap_mean(values, seed=7)
    assert first == block_bootstrap_mean(values, seed=7)
    assert first["estimate"] == pytest.approx(values.mean())
    assert first["ci_low"] < first["estimate"] < first["ci_high"]

    constant = block_bootstrap_mean(np.full(30, 2.5))
    assert constant["ci_low"] == constant["ci_high"] == 2.5
    with pytest.raises(ValueError, match="finite"):
        block_bootstrap_mean(np.array([1.0, np.nan]))


def test_block_bootstrap_wraps_around_circularly():
    # With blocks as long as the series every resample is a rotation, so the mean never varies.
    values = np.arange(14, dtype=float)
    result = block_bootstrap_mean(values, block_days=14, n_resamples=200)
    assert result["ci_low"] == result["ci_high"] == pytest.approx(values.mean())

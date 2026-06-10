"""Lifetable and Kaplan-Meier survival computations.

Produces a single DataFrame containing, for each treatment at each unique
event time:
    n_at_risk   — number alive and uncensored at the start of the interval
    n_deaths    — deaths during the interval
    n_censored  — censored during the interval
    qx          — probability of death in the interval  (d / n)
    px          — probability of surviving the interval  (1 - qx)
    lx          — survivorship (cumulative product of px)
    hx          — estimate of instantaneous hazard, adjusted for interval width
    km_lx       — Kaplan-Meier estimate of survivorship
    se_km       — Greenwood standard error of KM estimate
    km_ci_lo    — 95% CI lower bound for KM
    km_ci_hi    — 95% CI upper bound for KM
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _lifetable_one_treatment(df: pd.DataFrame) -> pd.DataFrame:
    """Compute lifetable for a single treatment group.

    Parameters
    ----------
    df : DataFrame
        Must have columns ``time`` and ``event`` (1=death, 0=censored).
        Pooled across all chambers for this treatment.
    """
    # Get all unique times, sorted
    times = sorted(df["time"].unique())

    records = []
    n_at_risk = len(df)
    cum_surv = 1.0
    greenwood_sum = 0.0
    na_H = 0.0       # Nelson-Aalen cumulative hazard
    na_var = 0.0     # Variance for NA CI

    for i, t in enumerate(times):
        at_t = df[df["time"] == t]
        d = int(at_t["event"].sum())          # deaths at time t
        c = int((at_t["event"] == 0).sum())   # censored at time t

        # Interval width for hazard calculation
        if i + 1 < len(times):
            dt = times[i + 1] - t
        else:
            dt = t - times[i - 1] if i > 0 else 1.0

        if n_at_risk > 0:
            qx = d / n_at_risk
            px = 1.0 - qx
        else:
            qx = 0.0
            px = 1.0

        cum_surv *= px

        # Greenwood's formula for SE of KM
        if n_at_risk > 0 and d > 0 and n_at_risk != d:
            greenwood_sum += d / (n_at_risk * (n_at_risk - d))

        se_km = cum_surv * np.sqrt(greenwood_sum) if greenwood_sum > 0 else 0.0

        # Hazard estimate (adjusted for interval width)
        # Using actuarial approximation: hx = 2*qx / ((1+px)*dt)
        if dt > 0 and (1 + px) > 0:
            hx = 2 * qx / ((1 + px) * dt)
        else:
            hx = 0.0

        # Nelson-Aalen cumulative hazard
        if n_at_risk > 0 and d > 0:
            na_H += d / n_at_risk
            na_var += d / (n_at_risk ** 2)

        na_se = np.sqrt(na_var)
        na_ci_lo = max(0.0, na_H - 1.96 * na_se)
        na_ci_hi = na_H + 1.96 * na_se

        records.append({
            "time": t,
            "n_at_risk": n_at_risk,
            "n_deaths": d,
            "n_censored": c,
            "qx": qx,
            "px": px,
            "lx": cum_surv,
            "hx": hx,
            "km_lx": cum_surv,
            "se_km": se_km,
            "km_ci_lo": max(0.0, cum_surv - 1.96 * se_km),
            "km_ci_hi": min(1.0, cum_surv + 1.96 * se_km),
            "na_H": na_H,
            "na_se": na_se,
            "na_ci_lo": na_ci_lo,
            "na_ci_hi": na_ci_hi,
        })

        n_at_risk -= (d + c)

    return pd.DataFrame(records)


def compute_lifetables(individual_data: pd.DataFrame) -> pd.DataFrame:
    """Compute lifetable statistics for all treatments.

    Parameters
    ----------
    individual_data : DataFrame
        Output of ``data_loader.load_experiment()``, with columns
        ``time``, ``event``, ``treatment``, etc.

    Returns
    -------
    DataFrame with a ``treatment`` column and all lifetable columns.
    """
    parts = []
    for treatment, grp in individual_data.groupby("treatment"):
        lt = _lifetable_one_treatment(grp)
        lt.insert(0, "treatment", treatment)
        parts.append(lt)

    return pd.concat(parts, ignore_index=True)


def compute_lifetables_per_chamber(individual_data: pd.DataFrame) -> pd.DataFrame:
    """Compute one lifetable per (treatment, chamber).

    Used by the QC viewer to draw an overlay of every chamber's KM curve
    inside a treatment, so outliers can be picked out by eye.

    Returns a DataFrame with columns
    ``treatment, chamber, time, n_at_risk, n_deaths, km_lx`` (plus all the
    other lifetable columns from :func:`_lifetable_one_treatment`).
    Chambers with fewer than 2 individuals are still included; chambers
    with no events show a flat km_lx=1.0 line.
    """
    if "chamber" not in individual_data.columns:
        return pd.DataFrame(
            columns=["treatment", "chamber", "time", "km_lx", "n_at_risk", "n_deaths"]
        )
    parts = []
    for (treatment, chamber), grp in individual_data.groupby(["treatment", "chamber"]):
        if len(grp) == 0:
            continue
        lt = _lifetable_one_treatment(grp)
        lt.insert(0, "chamber", chamber)
        lt.insert(0, "treatment", treatment)
        parts.append(lt)
    if not parts:
        return pd.DataFrame(
            columns=["treatment", "chamber", "time", "km_lx", "n_at_risk", "n_deaths"]
        )
    return pd.concat(parts, ignore_index=True)


def median_survival(lifetable: pd.DataFrame) -> pd.DataFrame:
    """Extract median survival time for each treatment.

    Returns a DataFrame with treatment, median_time, and the 95% CI bounds
    for the time at which KM crosses 0.5.
    """
    results = []
    for treatment, grp in lifetable.groupby("treatment"):
        below = grp[grp["km_lx"] <= 0.5]
        if len(below) > 0:
            median_t = below["time"].iloc[0]
        else:
            median_t = np.nan
        results.append({"treatment": treatment, "median_survival": median_t})
    return pd.DataFrame(results)


def mean_survival(individual_data: pd.DataFrame) -> pd.DataFrame:
    """Compute restricted mean survival time (RMST) for each treatment.

    Uses the area under the KM curve up to the minimum of the max observed
    times across treatments (common restriction time).
    """
    lt = compute_lifetables(individual_data)
    t_max = lt.groupby("treatment")["time"].max().min()

    results = []
    for treatment, grp in lt.groupby("treatment"):
        grp = grp[grp["time"] <= t_max].sort_values("time")
        times = grp["time"].values
        surv = grp["km_lx"].values

        # Trapezoidal integration of the survival curve. Prepend the origin
        # (t=0, S=1) so the initial [0, first_event] interval (area ≈
        # first_event × 1.0) is included — omitting it biases RMST low, and
        # because the first event time differs by arm the bias is unequal across
        # treatments (distorting RMST *differences*, not just levels). This
        # matches _km_mean_median_one_group, which already anchors the origin.
        if len(times) >= 1:
            times_full = np.concatenate([[0.0], times])
            surv_full = np.concatenate([[1.0], surv])
            area = np.trapezoid(surv_full, times_full)
        else:
            area = np.nan

        results.append({
            "treatment": treatment,
            "rmst": area,
            "restriction_time": t_max,
        })
    return pd.DataFrame(results)


def _km_mean_median_one_group(df: pd.DataFrame) -> dict:
    """Compute KM-based mean (RMST) and median for a single group.

    Parameters
    ----------
    df : DataFrame with ``time`` and ``event`` columns.
    """
    lt = _lifetable_one_treatment(df)

    # Median: first time KM <= 0.5
    below = lt[lt["km_lx"] <= 0.5]
    median_t = float(below["time"].iloc[0]) if len(below) > 0 else np.nan

    # Mean (RMST to max observed time)
    times = lt["time"].values
    surv = lt["km_lx"].values
    if len(times) > 1:
        # Prepend time 0, surv 1.0 for proper integration
        times_full = np.concatenate([[0.0], times])
        surv_full = np.concatenate([[1.0], surv])
        rmst = float(np.trapezoid(surv_full, times_full))
    else:
        rmst = np.nan

    return {"median": median_t, "mean_rmst": rmst, "t_max": float(times[-1]) if len(times) > 0 else np.nan}


def _top_percentile_mean(df: pd.DataFrame, percentile: float) -> float:
    """Mean lifespan of the longest-lived fraction of *dead* individuals.

    Only meaningful when censoring is minimal (assume_censored=False).

    Parameters
    ----------
    df : DataFrame with ``time`` and ``event`` columns.
    percentile : fraction to keep, e.g. 0.10 for top 10%.
    """
    deaths = df.loc[df["event"] == 1, "time"].sort_values(ascending=False)
    if len(deaths) == 0:
        return np.nan
    n_keep = max(1, int(np.ceil(len(deaths) * percentile)))
    return float(deaths.iloc[:n_keep].mean())


def lifespan_statistics(
    individual_data: pd.DataFrame,
    factors: list[str],
    assume_censored: bool = True,
) -> dict:
    """Compute mean and median lifespan statistics.

    Returns a dict with:
        treatment_stats : DataFrame — one row per treatment combination
        factor_stats    : DataFrame — one row per individual factor level
                          (e.g. all Males pooled, all 40x pooled)

    Columns in each DataFrame:
        group, n, n_deaths, n_censored, mean_rmst, median, t_max
        (and top_10pct_mean, top_5pct_mean when assume_censored=False and n>10)
    """

    def _stats_for_group(grp: pd.DataFrame, label: str) -> dict:
        n = len(grp)
        n_deaths = int(grp["event"].sum())
        n_censored = n - n_deaths
        km = _km_mean_median_one_group(grp)

        rec = {
            "group": label,
            "n": n,
            "n_deaths": n_deaths,
            "n_censored": n_censored,
            "mean_rmst": round(km["mean_rmst"], 2) if not np.isnan(km["mean_rmst"]) else np.nan,
            "median": round(km["median"], 2) if not np.isnan(km["median"]) else np.nan,
            "t_max": round(km["t_max"], 2) if not np.isnan(km["t_max"]) else np.nan,
        }

        if not assume_censored and n_deaths > 10:
            rec["top_10pct_mean"] = round(_top_percentile_mean(grp, 0.10), 2)
            rec["top_5pct_mean"] = round(_top_percentile_mean(grp, 0.05), 2)

        return rec

    # Per treatment combination
    treatment_rows = []
    for treatment, grp in individual_data.groupby("treatment"):
        treatment_rows.append(_stats_for_group(grp, treatment))
    treatment_stats = pd.DataFrame(treatment_rows)

    # Per individual factor level
    factor_rows = []
    for factor in factors:
        for level, grp in individual_data.groupby(factor):
            label = f"{factor}={level}"
            factor_rows.append(_stats_for_group(grp, label))
    factor_stats = pd.DataFrame(factor_rows)

    return {
        "treatment_stats": treatment_stats,
        "factor_stats": factor_stats,
    }


def survival_quantiles(
    lifetable: pd.DataFrame,
    quantiles: list[float] | None = None,
) -> pd.DataFrame:
    """Compute survival time quantiles from the KM lifetable.

    Returns the time at which KM survival crosses each threshold for each
    treatment.

    Parameters
    ----------
    lifetable : DataFrame from ``compute_lifetables()``
    quantiles : survival fractions at which to report time, e.g. [0.90, 0.75, 0.50, 0.25, 0.10]

    Returns
    -------
    DataFrame with treatment and one column per quantile label.
    """
    if quantiles is None:
        quantiles = [0.90, 0.75, 0.50, 0.25, 0.10]

    records = []
    for treatment, grp in lifetable.groupby("treatment"):
        row: dict = {"treatment": treatment}
        for q in quantiles:
            below = grp[grp["km_lx"] <= q]
            col_name = f"S={int(q * 100)}%"
            row[col_name] = float(below["time"].iloc[0]) if len(below) > 0 else np.nan
        records.append(row)

    return pd.DataFrame(records)


def at_risk_table(
    lifetable: pd.DataFrame,
    timepoints: list[float] | None = None,
) -> pd.DataFrame:
    """Build a number-at-risk table at specified timepoints.

    Parameters
    ----------
    lifetable : DataFrame from ``compute_lifetables()``
    timepoints : specific times at which to report n_at_risk (auto-chosen if None)

    Returns
    -------
    DataFrame with treatments as rows and timepoints as columns.
    """
    all_times = sorted(lifetable["time"].unique())
    if timepoints is None:
        # Pick ~8 evenly spaced timepoints
        n_pts = min(8, len(all_times))
        indices = np.linspace(0, len(all_times) - 1, n_pts, dtype=int)
        timepoints = [all_times[i] for i in indices]

    records = []
    for treatment, grp in lifetable.groupby("treatment"):
        row: dict = {"treatment": treatment}
        for tp in timepoints:
            # Find the row just before or at this timepoint
            at_or_before = grp[grp["time"] <= tp]
            if len(at_or_before) == 0:
                n_risk = grp["n_at_risk"].iloc[0] if len(grp) > 0 else 0
            else:
                last_row = at_or_before.iloc[-1]
                n_risk = int(last_row["n_at_risk"] - last_row["n_deaths"] - last_row["n_censored"])
                n_risk = max(0, n_risk)
            row[f"t={tp:.0f}"] = n_risk
        records.append(row)

    return pd.DataFrame(records)

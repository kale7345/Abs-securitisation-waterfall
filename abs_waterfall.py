"""A compact sequential-pay asset-backed securities waterfall model."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

POOL_PRINCIPAL = 100_000_000.0
WAC = 0.06
POOL_TERM = 60
TRANCHES = {"A": 0.70, "B": 0.20, "C": 0.10}
TRANCHE_CPN = {"A": 0.035, "B": 0.055, "C": 0.0}
RECOVERY = 0.40


def month_pool_cfs(
    balance: float,
    scheduled_prin: float,
    m_def: float,
    m_prepay: float,
) -> tuple[float, float, float, float]:
    """Return ending balance, interest, principal proceeds, and credit losses."""
    if balance < 0 or scheduled_prin < 0:
        raise ValueError("Balance and scheduled principal must be non-negative")
    if not 0 <= m_def < 1 or not 0 <= m_prepay < 1:
        raise ValueError("Monthly default and prepayment rates must be in [0, 1)")

    defaults = balance * m_def
    recoveries = defaults * RECOVERY
    losses = defaults - recoveries
    prepayments = (balance - defaults) * m_prepay
    scheduled = min(scheduled_prin, balance - defaults - prepayments)
    interest = (balance - defaults / 2) * WAC / 12
    end_balance = balance - defaults - prepayments - scheduled
    principal_available = scheduled + prepayments + recoveries
    return end_balance, interest, principal_available, losses


def annual_to_monthly(rate: float) -> float:
    """Convert an effective annual rate to an effective monthly rate."""
    if not 0 <= rate < 1:
        raise ValueError("Annual rates must be in [0, 1)")
    return 1 - (1 - rate) ** (1 / 12)


def run_waterfall(
    default_rate_annual: float,
    prepay_rate_annual: float,
) -> pd.DataFrame:
    """Run a monthly pool and sequential-pay tranche waterfall."""
    monthly_default = annual_to_monthly(default_rate_annual)
    monthly_prepay = annual_to_monthly(prepay_rate_annual)
    tranche_balances = {
        tranche: POOL_PRINCIPAL * percentage
        for tranche, percentage in TRANCHES.items()
    }
    scheduled_profile = np.full(POOL_TERM, POOL_PRINCIPAL / POOL_TERM)
    pool_balance = POOL_PRINCIPAL
    rows: list[dict[str, float | int]] = []

    for month, scheduled_principal in enumerate(scheduled_profile, start=1):
        if pool_balance <= 0.01:
            break

        pool_balance_next, interest, principal_available, losses = month_pool_cfs(
            pool_balance,
            float(scheduled_principal),
            monthly_default,
            monthly_prepay,
        )

        tranche_losses = {tranche: 0.0 for tranche in TRANCHES}
        remaining_loss = losses
        for tranche in ("C", "B", "A"):
            tranche_loss = min(tranche_balances[tranche], remaining_loss)
            tranche_losses[tranche] = tranche_loss
            tranche_balances[tranche] -= tranche_loss
            remaining_loss -= tranche_loss
        if remaining_loss > 0.01:
            raise ArithmeticError("Credit losses exceed total tranche balance")

        interest_available = interest
        tranche_interest = {tranche: 0.0 for tranche in TRANCHES}
        for tranche in ("A", "B"):
            interest_due = tranche_balances[tranche] * TRANCHE_CPN[tranche] / 12
            tranche_interest[tranche] = min(interest_due, interest_available)
            interest_available -= tranche_interest[tranche]
        tranche_interest["C"] = interest_available

        principal_remaining = principal_available
        tranche_principal = {tranche: 0.0 for tranche in TRANCHES}
        for tranche in TRANCHES:
            tranche_principal[tranche] = min(
                tranche_balances[tranche], principal_remaining
            )
            tranche_balances[tranche] -= tranche_principal[tranche]
            principal_remaining -= tranche_principal[tranche]

        row: dict[str, float | int] = {
            "Month": month,
            "Pool_Balance": pool_balance_next,
            "Pool_Interest": interest,
            "Principal_Available": principal_available,
            "Losses": losses,
        }
        for tranche in TRANCHES:
            row[f"{tranche}_Balance"] = tranche_balances[tranche]
            row[f"{tranche}_Int"] = tranche_interest[tranche]
            row[f"{tranche}_Prin"] = tranche_principal[tranche]
            row[f"{tranche}_Loss"] = tranche_losses[tranche]
        rows.append(row)
        pool_balance = pool_balance_next

    return pd.DataFrame(rows)


def wal(df: pd.DataFrame, tranche: str, notional: float | None = None) -> float:
    """Calculate weighted average life in years from principal distributions."""
    del notional
    principal = df[f"{tranche}_Prin"].to_numpy()
    months = df["Month"].to_numpy()
    total_principal = principal.sum()
    if total_principal <= 0:
        return 0.0
    return float((principal * months).sum() / total_principal / 12)


def breakeven_default(target: str = "B", prepay_rate_annual: float = 0.0) -> float:
    """Find the annual default rate at which the target tranche first takes loss."""
    if target not in ("A", "B"):
        raise ValueError("Breakeven target must be tranche 'A' or 'B'")

    low, high = 0.0, 0.50
    if run_waterfall(high, prepay_rate_annual)[f"{target}_Loss"].sum() <= 0:
        raise ValueError(f"No {target} tranche loss occurs by a 50% annual default rate")
    for _ in range(60):
        midpoint = (low + high) / 2
        losses = run_waterfall(midpoint, prepay_rate_annual)[f"{target}_Loss"].sum()
        if losses > 0:
            high = midpoint
        else:
            low = midpoint
    return (low + high) / 2


def run_scenarios(output_dir: Path = Path("outputs")) -> dict[str, pd.DataFrame]:
    """Write base and stress scenario CSVs and the tranche-balance chart."""
    output_dir.mkdir(parents=True, exist_ok=True)
    scenarios = {
        "base": run_waterfall(0.02, 0.10),
        "stress": run_waterfall(0.10, 0.02),
    }
    for name, dataframe in scenarios.items():
        dataframe.to_csv(output_dir / f"{name}_scenario.csv", index=False)

    colors = {"A": "#176b87", "B": "#b54732", "C": "#4d7c45"}
    figure, axis = plt.subplots(figsize=(10, 6), layout="constrained")
    for name, dataframe in scenarios.items():
        line_style = "-" if name == "base" else "--"
        for tranche, color in colors.items():
            axis.plot(
                dataframe["Month"],
                dataframe[f"{tranche}_Balance"] / 1_000_000,
                color=color,
                linestyle=line_style,
                label=f"{tranche} {name}",
            )
    axis.set(title="Sequential-Pay ABS Tranche Balances", xlabel="Month", ylabel="Outstanding balance ($m)")
    axis.grid(alpha=0.25)
    axis.legend(ncols=2, frameon=False)
    figure.savefig(output_dir / "tranche_balances.png", dpi=160)
    plt.close(figure)
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()

    scenarios = run_scenarios(args.output_dir)
    base = scenarios["base"]
    stress = scenarios["stress"]
    print(f"Base-case total losses: ${base['Losses'].sum():,.0f}")
    print(f"Stress-case total losses: ${stress['Losses'].sum():,.0f}")
    print("Base-case WAL (years): " + ", ".join(
        f"{tranche}={wal(base, tranche):.2f}" for tranche in TRANCHES
    ))
    print(f"B-tranche breakeven annual defaults: {breakeven_default('B'):.2%}")
    print(f"Wrote scenarios and chart to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
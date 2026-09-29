# ABS Waterfall Model

A small Python model of a $100 million, 60-month, sequential-pay asset-backed security. It runs the collateral cash flows, allocates credit losses from equity upward, pays tranche interest and principal, compares base and stress scenarios, and calculates weighted average life (WAL) and mezzanine breakeven defaults.

## Environment Setup

The workspace uses a project-local `.venv` running Python 3.14. In VS Code, select `.venv` as the workspace interpreter if it is not already selected. The virtual environment is local and excluded from version control.

From PowerShell at the project root:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If the project environment already exists, skip the `venv` command. On macOS or Linux, create it with `python3 -m venv .venv`, then use `.venv/bin/python` in place of `.venv\Scripts\python.exe` below.

## Run

Run the complete model, write both scenario CSVs and the tranche-balance chart, and print summary metrics:

```powershell
.\.venv\Scripts\python.exe abs_waterfall.py
```

Outputs are written to `outputs/` by default. Pass `--output-dir path` to choose another location.

Run all model checkpoints and regression tests:

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

## Build Sequence And Checkpoints

The order below mirrors the model implementation and the tests. `test_abs_waterfall.py` exercises these assumptions and invariants.

1. **Deal structure:** A/B/C are 70%/20%/10% of the pool, so A has 30% subordination beneath it.
2. **Monthly collateral cash flows:** With a $100m beginning balance, no defaults or prepayments, and scheduled principal of $100m/60, monthly interest is $500,000 and scheduled principal is about $1.667m.
3. **Rate conversion:** Effective annual defaults and prepayments are converted using `1 - (1 - annual_rate) ** (1 / 12)`.
4. **Monthly loop:** The pool amortizes to zero. In the 2% default / 10% prepayment base case, losses are positive in every active month.
5. **Loss allocation:** Losses are reverse-sequential: C, then B, then A. In the base case all credit losses stay in C; the stress case exhausts C before B is impaired.
6. **Interest waterfall:** A and B coupons are paid senior-first from pool interest; remaining interest is assigned to C. Interest and principal cash are deliberately kept separate to avoid spending principal twice.
7. **Principal waterfall:** Principal pays A, then B, then C. Each junior tranche starts receiving principal only after the senior balance is zero.
8. **WAL:** Base case WAL is approximately A 1.27, B 3.07, and C 3.72 years.
9. **Scenarios:** Base is 2% annual defaults / 10% annual prepayment; stress is 10% / 2%. The base case impairs only C; stress impairs C and B.
10. **Breakeven:** B's first-loss threshold is about 8.00% annual defaults when prepayments are zero. The bisection function rejects C because its zero subordination makes that threshold uninformative.
11. **Outputs:** `outputs/base_scenario.csv`, `outputs/stress_scenario.csv`, and `outputs/tranche_balances.png`. Solid lines show base balances; dashed lines show stress balances.

## Model Assumptions

- Scheduled principal is a fixed straight-line amount of original pool principal per month, capped at the remaining performing balance. This is a simplified amortization profile, not a level-payment loan schedule.
- Defaults happen on beginning pool balance. Recoveries are 40% of defaults and are available as principal in the same month; the remaining 60% is allocated as a loss.
- Prepayments apply to balance remaining after defaults. Pool interest follows the supplied approximation, `(beginning_balance - defaults / 2) * WAC / 12`.
- Tranche coupon interest is calculated after that month's losses and before principal paydown. If pool interest is insufficient, unpaid A/B interest is not accrued, and principal is not diverted to cover the shortfall.
- WAL uses principal distributed by month and is expressed in years. It is not duration and does not discount cash flows.
- Breakeven is the annual default assumption that first causes the target tranche to take a credit loss, with the selected prepayment assumption held fixed.

This is an educational model, not an offering, valuation, or investment recommendation. It omits triggers, servicing costs, taxes, delinquency timing, recovery lag, revolving periods, and interest shortfall carry-forward.

## Interview Notes

- **Subordination:** Junior tranches absorb losses first; credit enhancement is the principal beneath a tranche that can absorb losses before it is affected.
- **Sequential paydown:** Senior investors receive principal first, generally shortening senior WAL; junior investors bear more risk and receive higher coupons or residual cash flow.
- **Recoveries:** Recoveries are modeled as principal proceeds, separately from the unrecovered amount that becomes a credit loss.
- **Bisection:** The first-loss boundary is monotone in the modeled annual default assumption. Sixty iterations greatly exceed the precision supported by the input assumptions, but provide a stable numerical threshold.
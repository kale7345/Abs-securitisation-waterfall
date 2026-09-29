import tempfile
import unittest
from pathlib import Path

import numpy as np

import abs_waterfall as model


class DealAndPoolTests(unittest.TestCase):
    def test_deal_structure_and_credit_enhancement(self) -> None:
        tranche_balances = {
            tranche: model.POOL_PRINCIPAL * share
            for tranche, share in model.TRANCHES.items()
        }
        self.assertAlmostEqual(sum(model.TRANCHES.values()), 1.0)
        self.assertEqual(tranche_balances, {"A": 70_000_000, "B": 20_000_000, "C": 10_000_000})
        self.assertAlmostEqual(model.TRANCHES["B"] + model.TRANCHES["C"], 0.30)

    def test_one_month_pool_checkpoint(self) -> None:
        ending, interest, principal, losses = model.month_pool_cfs(
            100_000_000, 100_000_000 / 60, 0.0, 0.0
        )
        self.assertAlmostEqual(interest, 500_000)
        self.assertAlmostEqual(principal, 100_000_000 / 60)
        self.assertAlmostEqual(ending, 100_000_000 - principal)
        self.assertEqual(losses, 0.0)

    def test_annual_rates_compound_to_monthly(self) -> None:
        monthly_default = model.annual_to_monthly(0.02)
        monthly_prepay = model.annual_to_monthly(0.10)
        self.assertAlmostEqual((1 - monthly_default) ** 12, 0.98)
        self.assertAlmostEqual((1 - monthly_prepay) ** 12, 0.90)


class WaterfallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = model.run_waterfall(0.02, 0.10)
        cls.stress = model.run_waterfall(0.10, 0.02)

    def test_base_loss_subordination(self) -> None:
        self.assertTrue((self.base["Losses"] > 0).all())
        self.assertGreater(self.base["C_Loss"].sum(), 0)
        self.assertEqual(self.base["B_Loss"].sum(), 0)
        self.assertEqual(self.base["A_Loss"].sum(), 0)

    def test_base_interest_waterfall(self) -> None:
        for tranche in ("A", "B"):
            balance_before_principal = (
                self.base[f"{tranche}_Balance"] + self.base[f"{tranche}_Prin"]
            )
            coupon_due = balance_before_principal * model.TRANCHE_CPN[tranche] / 12
            np.testing.assert_allclose(self.base[f"{tranche}_Int"], coupon_due)
        self.assertGreater(self.base["C_Int"].nunique(), 1)

    def test_sequential_principal_and_pool_runoff(self) -> None:
        self.assertTrue((self.base["Pool_Balance"].diff().dropna() <= 0).all())
        self.assertAlmostEqual(self.base["Pool_Balance"].iloc[-1], 0.0, places=6)
        for tranche in model.TRANCHES:
            self.assertAlmostEqual(self.base[f"{tranche}_Balance"].iloc[-1], 0.0, places=6)
        b_paid = self.base["B_Prin"] > 0
        c_paid = self.base["C_Prin"] > 0
        self.assertTrue((self.base.loc[b_paid, "A_Balance"] == 0).all())
        self.assertTrue((self.base.loc[c_paid, ["A_Balance", "B_Balance"]] == 0).all().all())

    def test_base_weighted_average_life(self) -> None:
        expected = {"A": 1.3, "B": 3.1, "C": 3.7}
        for tranche, years in expected.items():
            self.assertAlmostEqual(model.wal(self.base, tranche), years, delta=0.12)

    def test_stress_scenario_exhausts_equity_then_hits_mezzanine(self) -> None:
        self.assertGreater(self.stress["Losses"].sum(), self.base["Losses"].sum())
        self.assertAlmostEqual(self.stress["C_Loss"].sum(), 10_000_000, places=4)
        self.assertGreater(self.stress["B_Loss"].sum(), 0)
        self.assertEqual(self.stress["A_Loss"].sum(), 0)

    def test_cash_and_balance_conservation(self) -> None:
        for scenario in (self.base, self.stress):
            principal_columns = [f"{tranche}_Prin" for tranche in model.TRANCHES]
            interest_columns = [f"{tranche}_Int" for tranche in model.TRANCHES]
            np.testing.assert_allclose(
                scenario[principal_columns].sum(axis=1),
                scenario["Principal_Available"],
                atol=1e-6,
            )
            self.assertTrue(
                (scenario[interest_columns].sum(axis=1) <= scenario["Pool_Interest"] + 1e-6).all()
            )
            tranche_balance = scenario[[f"{tranche}_Balance" for tranche in model.TRANCHES]].sum(axis=1)
            np.testing.assert_allclose(tranche_balance, scenario["Pool_Balance"], atol=1e-6)

    def test_b_tranche_breakeven(self) -> None:
        rate = model.breakeven_default("B")
        self.assertAlmostEqual(rate, 0.08, delta=0.005)
        self.assertEqual(model.run_waterfall(rate - 1e-5, 0.0)["B_Loss"].sum(), 0.0)
        self.assertGreater(model.run_waterfall(rate + 1e-5, 0.0)["B_Loss"].sum(), 0.0)
        with self.assertRaises(ValueError):
            model.breakeven_default("C")

    def test_outputs_include_scenarios_and_chart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            scenarios = model.run_scenarios(output_dir)
            self.assertEqual(set(scenarios), {"base", "stress"})
            self.assertTrue((output_dir / "base_scenario.csv").is_file())
            self.assertTrue((output_dir / "stress_scenario.csv").is_file())
            self.assertTrue((output_dir / "tranche_balances.png").is_file())


if __name__ == "__main__":
    unittest.main()
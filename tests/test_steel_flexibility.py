import sys
import types
import unittest
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

sys.modules.setdefault("pypsa", types.SimpleNamespace())
sys.modules.setdefault("geopandas", types.SimpleNamespace())

from Industry_constraints import (  # noqa: E402
    add_annual_steel_production_constraint,
    annual_steel_target,
    steel_process_links,
)
from Industry_model import (  # noqa: E402
    add_steel_production,
    get_steel_process_flexibility,
)


class FakeNetwork:
    def __init__(self):
        self.buses = pd.DataFrame({"carrier": ["AC"]}, index=["DE1 0"])
        self.links = pd.DataFrame()
        self.calls = []

    def add(self, component, name=None, **kwargs):
        self.calls.append((component, name, kwargs))
        if component == "Link":
            for key, value in kwargs.items():
                self.links.loc[name, key] = value


def steel_energy(processes):
    return pd.DataFrame(
        {
            process: {
                "elec": 2.0,
                "process emission": 0.1,
                "methane": 0.2,
                "hydrogen": 0.3,
                "furnaces heat": 0.4,
                "mc_per_t": 5.0,
                "an_inv_per_yt": 10.0,
            }
            for process in processes
        }
    )


def steel_feedstock(processes):
    return pd.DataFrame(
        {process: {"steel scrap": 0.5} for process in processes}
    )


class SteelFlexibilityTests(unittest.TestCase):
    def test_process_flexibility_orders_eaf_as_most_flexible(self):
        isw = get_steel_process_flexibility("ISW")
        dri = get_steel_process_flexibility("H2-DRI+EAF")
        eaf = get_steel_process_flexibility("EAF")

        self.assertEqual(isw["must_run"], 1.0)
        self.assertLess(eaf["must_run"], dri["must_run"])
        self.assertLess(dri["must_run"], isw["must_run"])
        self.assertGreater(eaf["ramp_limit_up"], dri["ramp_limit_up"])
        self.assertGreater(dri["ramp_limit_up"], isw["ramp_limit_up"])

    def test_add_steel_production_adds_storage_and_flexible_link_attrs(self):
        processes = ["ISW", "H2-DRI+EAF", "EAF"]
        n = FakeNetwork()

        add_steel_production(
            n,
            steel_load=8760,
            steel_energy=steel_energy(processes),
            steel_feedstock=steel_feedstock(processes),
            max_scrap=100,
        )

        stores = {name: kwargs for component, name, kwargs in n.calls if component == "Store"}
        self.assertIn("DE steel inventory", stores)
        self.assertTrue(stores["DE steel inventory"]["e_nom_extendable"])
        self.assertTrue(stores["DE steel inventory"]["e_cyclic"])

        self.assertEqual(n.links.loc["DE1 0 steel ISW", "p_min_pu"], 1.0)
        self.assertEqual(n.links.loc["DE1 0 steel EAF", "p_min_pu"], 0.0)
        self.assertEqual(n.links.loc["DE1 0 steel EAF", "ramp_limit_up"], 1.0)
        self.assertLess(
            n.links.loc["DE1 0 steel ISW", "ramp_limit_up"],
            n.links.loc["DE1 0 steel EAF", "ramp_limit_up"],
        )

    def test_annual_steel_constraint_uses_only_steel_links_and_snapshot_weights(self):
        snapshots = pd.Index(["t0", "t1", "t2"])
        n = types.SimpleNamespace()
        n.links = pd.DataFrame(
            {
                "carrier": ["steel EAF", "steel ISW", "hvc steamcracker"],
                "efficiency": [0.5, 0.25, 99.0],
            },
            index=["DE steel EAF", "DE steel ISW", "DE hvc"],
        )
        n.snapshot_weightings = pd.DataFrame({"objective": [2.0, 2.0, 2.0]}, index=snapshots)
        link_p = pd.DataFrame(1.0, index=snapshots, columns=n.links.index)
        captured = {}

        def define_constraints(network, lhs, sense, rhs, component, name):
            captured.update(
                lhs=lhs,
                sense=sense,
                rhs=rhs,
                component=component,
                name=name,
            )

        def get_var(network, component, attribute):
            self.assertEqual(component, "Link")
            self.assertEqual(attribute, "p")
            return link_p

        def linexpr(pair):
            coefficients, variables = pair
            return coefficients * variables

        add_annual_steel_production_constraint(
            n,
            snapshots,
            steel_load=8760,
            define_constraints=define_constraints,
            get_var=get_var,
            linexpr=linexpr,
        )

        self.assertEqual(list(steel_process_links(n)), ["DE steel EAF", "DE steel ISW"])
        self.assertEqual(captured["sense"], "=")
        self.assertEqual(captured["component"], "Link")
        self.assertEqual(captured["name"], "steel annual production")
        self.assertEqual(captured["rhs"], annual_steel_target(n, snapshots, 8760))
        self.assertEqual(captured["rhs"], 6000)
        self.assertEqual(captured["lhs"], 4.5)


if __name__ == "__main__":
    unittest.main()

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pypsa



DEFAULT_NETWORK = "../results/post-networks/solved_coupled_Mat_today_H2_84.nc"
DEFAULT_OUTPUT_DIR = "../results/inspection"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Inspect solved industry/PyPSA results, with a focus on flexible steel production."
    )
    parser.add_argument(
        "--network",
        default=DEFAULT_NETWORK,
        help=f"Path to solved network file. Default: {DEFAULT_NETWORK}",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Folder for CSV and plot outputs. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--steel-load-kt",
        type=float,
        default=None,
        help="Annual steel demand in kt/y. If omitted, the script reports actual output only.",
    )
    return parser.parse_args()


def save_plot(series_or_frame, path, title=None, ylabel=None):
    ax = series_or_frame.plot(figsize=(12, 4))
    if title:
        ax.set_title(title)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.figure.tight_layout()
    ax.figure.savefig(path, dpi=150)
    plt.close(ax.figure)


def steel_process_links(n):
    return n.links[n.links.carrier.fillna("").str.startswith("steel ")].index


def snapshot_weights(n):
    if "objective" in n.snapshot_weightings.columns:
        return n.snapshot_weightings.objective
    return pd.Series(1.0, index=n.snapshots)


def inspect_basic_results(n, output_dir):
    print("\n=== Basic solved network checks ===")
    print(f"Objective: {n.objective:,.2f}")
    print(f"Snapshots: {len(n.snapshots)}")
    print(f"Components: {', '.join(sorted(n.components.keys()))}")

    statistics = n.statistics()
    statistics.to_csv(output_dir / "statistics.csv")
    print("\nTop-level statistics written to statistics.csv")
    print(statistics.head(20))


def inspect_steel(n, output_dir, steel_load_kt=None):
    links = steel_process_links(n)
    if len(links) == 0:
        print("\nNo steel process links found.")
        return

    print("\n=== Steel process capacities and flexibility ===")
    columns = [
        "carrier",
        "p_nom_opt",
        "p_min_pu",
        "ramp_limit_up",
        "ramp_limit_down",
        "efficiency",
    ]
    available_columns = [column for column in columns if column in n.links.columns]
    steel_link_table = n.links.loc[links, available_columns]
    steel_link_table.to_csv(output_dir / "steel_link_capacities.csv")
    print(steel_link_table)

    dispatch = n.links_t.p0[links]
    output = dispatch.mul(n.links.loc[links, "efficiency"], axis=1)
    weights = snapshot_weights(n)
    weighted_output = output.mul(weights, axis=0)

    dispatch.to_csv(output_dir / "steel_dispatch_p0.csv")
    output.to_csv(output_dir / "steel_output_t_per_h.csv")

    print("\n=== Steel annual production ===")
    by_process = weighted_output.sum()
    by_process.to_csv(output_dir / "steel_annual_output_by_process_t.csv")
    print(by_process)
    actual = by_process.sum()
    print(f"\nActual weighted steel output: {actual:,.2f} t")

    if steel_load_kt is not None:
        target = steel_load_kt * 1e3 * weights.sum() / 8760
        difference = actual - target
        print(f"Scaled target: {target:,.2f} t")
        print(f"Difference: {difference:,.6f} t")

    save_plot(
        dispatch,
        output_dir / "steel_dispatch_p0.png",
        title="Steel process dispatch",
        ylabel="Input power / activity",
    )
    save_plot(
        output,
        output_dir / "steel_output.png",
        title="Steel output by process",
        ylabel="t steel / h",
    )
    save_plot(
        dispatch.diff().dropna(how="all"),
        output_dir / "steel_dispatch_ramps.png",
        title="Steel process ramping",
        ylabel="Delta p0",
    )

    inventory = "DE steel inventory"
    if inventory in n.stores.index:
        print("\n=== Steel inventory ===")
        print(n.stores.loc[[inventory]])
        n.stores.loc[[inventory]].to_csv(output_dir / "steel_inventory_store.csv")
        if inventory in n.stores_t.e.columns:
            n.stores_t.e[inventory].to_csv(output_dir / "steel_inventory_state_t.csv")
            save_plot(
                n.stores_t.e[inventory],
                output_dir / "steel_inventory_state.png",
                title="Steel inventory state of charge",
                ylabel="t steel",
            )
    else:
        print("\nDE steel inventory store not found.")


def inspect_system_interaction(n, output_dir):
    price_buses = [
        bus
        for bus in ["DE1 0", "DE1 0 H2", "DE gas for industry", "DE oil for industry"]
        if bus in n.buses_t.marginal_price.columns
    ]
    if not price_buses:
        print("\nNo selected price buses found.")
        return

    prices = n.buses_t.marginal_price[price_buses]
    prices.to_csv(output_dir / "selected_marginal_prices.csv")
    save_plot(
        prices,
        output_dir / "selected_marginal_prices.png",
        title="Selected marginal prices",
        ylabel="EUR/MWh",
    )

    links = steel_process_links(n)
    if "DE1 0" in n.buses_t.marginal_price.columns and len(links) > 0:
        output = n.links_t.p0[links].mul(n.links.loc[links, "efficiency"], axis=1).sum(axis=1)
        fig, ax = plt.subplots(figsize=(12, 4))
        n.buses_t.marginal_price["DE1 0"].plot(ax=ax, label="DE1 0 electricity price")
        ax.set_ylabel("EUR/MWh")
        ax2 = ax.twinx()
        output.plot(ax=ax2, color="tab:orange", label="Total steel output")
        ax2.set_ylabel("t steel / h")
        ax.set_title("Steel output versus electricity price")
        lines, labels = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines + lines2, labels + labels2, loc="best")
        fig.tight_layout()
        fig.savefig(output_dir / "steel_output_vs_electricity_price.png", dpi=150)
        plt.close(fig)


def main():
    args = parse_args()
    network_path = Path(args.network)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading network: {network_path}")
    n = pypsa.Network(network_path)

    inspect_basic_results(n, output_dir)
    inspect_steel(n, output_dir, steel_load_kt=args.steel_load_kt)
    inspect_system_interaction(n, output_dir)

    print(f"\nInspection files written to: {output_dir.resolve()}")


if __name__ == "__main__":
    main()

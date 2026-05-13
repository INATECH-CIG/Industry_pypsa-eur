import pandas as pd


def steel_process_links(n):
    carriers = n.links.carrier.fillna("")
    return carriers[carriers.str.startswith("steel ")].index


def snapshot_weights(n, snapshots):
    if hasattr(n, "snapshot_weightings"):
        for column in ["objective", "generators", "stores"]:
            if column in n.snapshot_weightings.columns:
                return n.snapshot_weightings.loc[snapshots, column]
    return pd.Series(1.0, index=snapshots)


def annual_steel_target(n, snapshots, steel_load):
    weights = snapshot_weights(n, snapshots)
    return steel_load * 1e3 * weights.sum() / 8760


def add_annual_steel_production_constraint(
    n,
    snapshots,
    steel_load,
    define_constraints,
    get_var,
    linexpr,
):
    links = steel_process_links(n)
    if len(links) == 0:
        return

    weights = snapshot_weights(n, snapshots)
    link_p = get_var(n, "Link", "p").loc[snapshots, links]
    coefficients = pd.DataFrame(
        1.0,
        index=snapshots,
        columns=links,
    )
    coefficients = coefficients.mul(weights, axis=0)
    coefficients = coefficients.mul(n.links.loc[links, "efficiency"], axis=1)

    yearly_steel = linexpr((coefficients, link_p)).sum().sum()
    define_constraints(
        n,
        yearly_steel,
        "=",
        annual_steel_target(n, snapshots, steel_load),
        "Link",
        "steel annual production",
    )

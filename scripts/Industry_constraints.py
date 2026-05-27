import pandas as pd


HOURS_PER_YEAR = 8760


def steel_process_links(n):
    carriers = n.links.carrier.fillna("")
    return carriers[carriers.str.startswith("steel ")].index


def snapshot_weights(n, snapshots):
    if hasattr(n, "snapshot_weightings"):
        for column in ["objective", "generators", "stores"]:
            if column in n.snapshot_weightings.columns:
                return n.snapshot_weightings.loc[snapshots, column]
    return pd.Series(infer_snapshot_step_hours(snapshots), index=snapshots)


def infer_snapshot_step_hours(snapshots):
    index = pd.Index(snapshots)
    if len(index) <= 1 or not pd.api.types.is_datetime64_any_dtype(index):
        return 1.0

    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return 1.0
    return deltas.median() / pd.Timedelta(hours=1)


def represented_hours(n, snapshots):
    weights = snapshot_weights(n, snapshots)
    return float(weights.sum())


def scale_annual_resource_to_snapshots(annual_resource, n, snapshots):
    return annual_resource * represented_hours(n, snapshots) / HOURS_PER_YEAR


def scale_steel_scrap_availability(n, snapshots, max_scrap):
    if "DE steel scrap" not in n.stores.index:
        return

    scaled_scrap = scale_annual_resource_to_snapshots(max_scrap * 1e3, n, snapshots)
    n.stores.loc["DE steel scrap", "e_initial"] = scaled_scrap
    n.stores.loc["DE steel scrap", "e_nom"] = scaled_scrap
    if "e_nom_max" in n.stores.columns:
        n.stores.loc["DE steel scrap", "e_nom_max"] = scaled_scrap


def annual_steel_target(n, snapshots, steel_load):
    return scale_annual_resource_to_snapshots(steel_load * 1e3, n, snapshots)


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

"""Read-only LPA/RocketCEA objective review; writes only the chosen output directory.

Run from the LPA repository:
  python -B tmp/OF_Objective_Review_20261011/reproduce_objective_comparison.py

The optimization implementation below is independent of LPA's optimizer.
Its CEA objects use LPA's adapter ONLY to reproduce the same reactant cards,
units, finite-area combustor, and safe native runtime directory.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
from scipy.optimize import minimize_scalar

from lpa.core.models import EngineDefinition, EquilibriumMode
from lpa.core.performance import RocketCEAAdapter, nozzle_regime, optimize_mixture_ratio
from lpa.core.propellants import rocketcea_names

G0 = 9.80665
CONTRACTION = 6.25
AMBIENT_BAR = 1.01325


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strict_json(value):
    if isinstance(value, dict):
        return {key: strict_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [strict_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def maximize(evaluate, metric, lower, upper):
    """Scan all 101 points, then bounded refine every local grid maximum."""
    xs = np.linspace(lower, upper, 101)
    ys = [evaluate(float(x))[metric] for x in xs]
    valid = [(float(x), float(y)) for x, y in zip(xs, ys) if math.isfinite(y)]
    if not valid:
        raise ValueError(f"no finite values for {metric}")
    candidates = [max(valid, key=lambda pair: pair[1])]
    for i in range(1, len(xs)-1):
        if math.isfinite(ys[i]) and ys[i] >= ys[i-1] and ys[i] >= ys[i+1]:
            def cost(x):
                y = evaluate(float(x))[metric]
                return -y if math.isfinite(y) else 1e20
            solved = minimize_scalar(cost, bounds=(float(xs[i-1]), float(xs[i+1])),
                                     method="bounded", options={"xatol": 1e-10, "maxiter": 100})
            if not solved.success:
                raise RuntimeError(f"bounded refinement failed: {solved.message}")
            candidates.append((float(solved.x), -float(solved.fun)))
    mr, score = max(candidates, key=lambda pair: pair[1])
    return {"mixture_ratio": mr, "objective_value": score, "point": evaluate(mr)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    options = parser.parse_args()
    output = options.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    began = time.perf_counter()
    adapter = RocketCEAAdapter()
    if not adapter.available:
        raise RuntimeError(f"real RocketCEA required: {adapter.unavailable_reason}")
    # Import after the adapter has configured the native safe runtime directory.
    from rocketcea import cea_obj, input_cards, py_cea
    cea_directory = Path(cea_obj.__file__).parent
    pins = {name: version(name) for name in ("rocketcea", "numpy", "scipy")}
    if pins["rocketcea"] != "1.2.3":
        raise RuntimeError(f"expected RocketCEA 1.2.3; got {pins['rocketcea']}")
    provenance = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": pins, "repository": str(REPO),
        "native_cea_banner": "NASA-GLENN CHEMICAL EQUILIBRIUM PROGRAM CEA, OCTOBER 18, 2002; NASA RP-1311 Parts I (1994) and II (1996)",
        "gravity_m_s2": G0, "contraction_area_ratio": CONTRACTION,
        "pressure_convention": "FAC Pc is injector-face pressure (bar)",
        "cstar_raw_definition": "CEA reference C*: gc*Pinj/App(2)*aw; App(2) is Fortran 1-based, Python rockt.app[1] = Pinj/Pinf",
        "cstar_injector_definition": "Cstar_raw*rockt.app[1] = Pinj*At/mdot, checked independently against throat density*sonic velocity",
        "ambient_definition": "Isp_vac - Pambient/Pinj * epsilon * Cstar_injector / g0, only epsilon 5 and attached screen",
        "optimization": "101 point full-range scan then SciPy bounded refinement of every local grid maximum, xatol=1e-10 (CEA numerical resolution still limits significant digits)",
        "cea_input_resolution": "Scalar O/F is written using %f (6 decimal places) by installed RocketCEA 1.2.3; displayed optimizer coordinates within the same rounded CEA card are equivalent",
        "flow_modes": {"shifting": {"frozen": 0, "frozenAtThroat": 0},
                       "throat_frozen": {"frozen": 1, "frozenAtThroat": 1, "FAC_nfz": 3}},
        "scope": "Ideal thermochemical objective comparison, fixed Pc/CR/epsilon/reactant cards; no experiment, thermal, injector, structural or whole-engine optimum claimed",
        "sources": [
            "https://rocketcea.readthedocs.io/en/latest/finite_area_comb.html",
            "https://rocketcea.readthedocs.io/en/latest/functions.html",
            "https://ntrs.nasa.gov/citations/19950013764",
        ],
        "source_hashes": {}, "reactant_cards": {},
    }
    for name in ("cea_obj.py", "cea_obj_w_units.py", "input_cards.py", "py_cea.f", "thermo.lib", "trans.lib"):
        path = cea_directory/name
        if path.exists():
            provenance["source_hashes"][name] = {"path": str(path), "sha256": sha(path)}
    for relative in ("lpa/core/performance.py", "lpa/core/propellants.py", "lpa/core/models.py"):
        provenance["source_hashes"][relative] = {"path": str(REPO/relative), "sha256": sha(REPO/relative)}
    provenance["source_hashes"]["reproduction_script"] = {"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__))}
    cases = [
        ("LOX_RP1", "RP-1", 1.0, 20.0, .5, 4.0, (5.0, 40.0)),
        ("LOX_Ethanol70wt", "Ethanol", .7, 20.0, .3, 3.0, (5.0, 40.0)),
        ("LOX_LH2", "LH2", 1.0, 100.0, 2.0, 8.0, (40.0,)),
    ]
    grids, optima, penalties, comparisons, detailed = [], [], [], [], []
    modes = [("shifting", EquilibriumMode.SHIFTING, 0, 0),
             ("throat_frozen", EquilibriumMode.FROZEN_AREA, 1, 1)]
    for propellant, fuel, fraction, pc, lower, upper, expansions in cases:
        engine = EngineDefinition(name=propellant, oxidizer="LOX", fuel=fuel,
                                  fuel_mass_fraction=fraction, chamber_pressure_bar=pc,
                                  mixture_ratio=(lower+upper)/2)
        cea = adapter._make_cea(engine, CONTRACTION)
        ox_name, fu_name = rocketcea_names(engine.oxidizer, engine.fuel,
                                          engine.oxidizer_mass_fraction, engine.fuel_mass_fraction)
        provenance["reactant_cards"][propellant] = {
            "oxidizer_cea_name": ox_name, "fuel_cea_name": fu_name,
            "oxidizer_card": input_cards.oxCards[ox_name], "fuel_card": input_cards.fuelCards[fu_name],
            "fuel_mass_fraction": fraction,
            "reactant_supply_override": None,
            "OF_definition": "oxidizer mass / total fuel mass, including diluent water",
        }
        for eps in expansions:
            for mode_name, mode, frozen, at_throat in modes:
                cache = {}
                base = {"propellants": propellant, "Pc_injector_bar": pc,
                        "CR": CONTRACTION, "epsilon": eps, "flow_mode": mode_name}
                def evaluate(mr):
                    # CEA card writer formats MR to 6 decimal places internally;
                    # preserve optimizer x in the output but do not imply 1e-10 physical precision.
                    key = float(mr)
                    if key in cache:
                        return cache[key]
                    raw_cstar = float(cea.get_Cstar(Pc=pc, MR=mr))
                    if frozen:
                        ivac, selected_cstar, tc = cea.getFrozen_IvacCstrTc(
                            Pc=pc, MR=mr, eps=eps, frozenAtThroat=at_throat)
                    else:
                        ivac, selected_cstar, tc = cea.get_IvacCstrTc(Pc=pc, MR=mr, eps=eps)
                    original_ambient, original_mode = (math.nan, "not_requested")
                    if eps == 5:
                        original_ambient, original_mode = cea.estimate_Ambient_Isp(
                            Pc=pc, MR=mr, eps=eps, Pamb=AMBIENT_BAR,
                            frozen=frozen, frozenAtThroat=at_throat)
                    raw = cea.cea_obj
                    # Optional getters/cache hits may leave global Fortran arrays
                    # from another query. Restore this exact selected case first.
                    raw.setupCards(Pc=pc, pc_units="bar", MR=mr, eps=eps,
                                   frozen=frozen, frozenAtThroat=at_throat)
                    app_factor = float(py_cea.rockt.app[1])
                    injector_cstar = float(selected_cstar)*app_factor
                    pe = float(py_cea.prtout.ppp[raw.i_exit])
                    pcomb = float(py_cea.prtout.ppp[raw.i_chm])
                    gamma = float(py_cea.prtout.gammas[raw.i_thrt])
                    rho_throat = 1e5/float(py_cea.prtout.vlm[raw.i_thrt])
                    sonic_throat = float(py_cea.rockt.sonvel[raw.i_thrt])
                    direct_cstar = pc*1e5/(rho_throat*sonic_throat)
                    regime = nozzle_regime(pc*1e5, pe*1e5, AMBIENT_BAR*1e5, gamma)
                    sea = (float(ivac)-AMBIENT_BAR/pc*eps*injector_cstar/G0
                           if eps == 5 and regime.startswith("attached") else math.nan)
                    point = {**base, "mixture_ratio": float(mr),
                             "raw_cstar_m_s": raw_cstar,
                             "selected_cstar_m_s": float(selected_cstar),
                             "injector_cstar_m_s": injector_cstar,
                             "direct_throat_massflux_cstar_m_s": direct_cstar,
                             "Pinj_over_Pinf": app_factor, "Pcomb_bar": pcomb,
                             "exit_pressure_bar": pe, "throat_gamma": gamma,
                             "vacuum_isp_s": float(ivac), "sea_level_isp_s": sea,
                             "original_rocketcea_ambient_isp_s": float(original_ambient),
                             "original_rocketcea_ambient_mode": original_mode,
                             "sea_level_regime": regime,
                             "combustion_end_temperature_k": float(tc)}
                    if not all(math.isfinite(point[x]) for x in ("raw_cstar_m_s", "injector_cstar_m_s", "vacuum_isp_s")):
                        raise RuntimeError(f"nonfinite real CEA result: {point}")
                    cache[key] = point
                    return point
                for mr in np.linspace(lower, upper, 101):
                    grids.append(evaluate(float(mr)))
                metrics = ["raw_cstar_m_s", "injector_cstar_m_s", "vacuum_isp_s"]
                if eps == 5:
                    metrics.append("sea_level_isp_s")
                solutions = {metric: maximize(evaluate, metric, lower, upper) for metric in metrics}
                lpa = optimize_mixture_ratio(engine, contraction_area_ratio=CONTRACTION,
                                             expansion_ratio=eps, ambient_pressure_atm=(1.0 if eps == 5 else 0.0),
                                             equilibrium_mode=mode, bounds=(lower, upper), cea_adapter=adapter)
                if lpa.source != "rocketcea":
                    raise RuntimeError(f"LPA optimizer did not use real RocketCEA: {lpa}")
                lp = evaluate(lpa.mixture_ratio)
                for metric, solution in solutions.items():
                    optima.append({**base, "objective": metric, "optimal_OF": solution["mixture_ratio"],
                                   "objective_value": solution["objective_value"],
                                   "raw_cstar_m_s": solution["point"]["raw_cstar_m_s"],
                                   "injector_cstar_m_s": solution["point"]["injector_cstar_m_s"],
                                   "vacuum_isp_s": solution["point"]["vacuum_isp_s"],
                                   "sea_level_isp_s": solution["point"]["sea_level_isp_s"],
                                   "sea_level_regime": solution["point"]["sea_level_regime"]})
                for target in ("vacuum_isp_s", "sea_level_isp_s"):
                    if target not in solutions:
                        continue
                    best = solutions[target]
                    for selection, selected in (
                        ("independent_max_raw_cstar", solutions["raw_cstar_m_s"]["point"]),
                        ("independent_max_injector_cstar", solutions["injector_cstar_m_s"]["point"]),
                        ("LPA_optimizer", lp)):
                        loss = best["objective_value"]-selected[target]
                        penalties.append({**base, "target": target, "selection": selection,
                                          "selected_OF": selected["mixture_ratio"], "optimal_OF": best["mixture_ratio"],
                                          "OF_shift": best["mixture_ratio"]-selected["mixture_ratio"],
                                          "selected_isp_s": selected[target], "optimal_isp_s": best["objective_value"],
                                          "isp_penalty_s": loss, "isp_penalty_percent": 100*loss/best["objective_value"]})
                comparisons.append({**base, "LPA_OF": lpa.mixture_ratio,
                                    "independent_max_raw_cstar_OF": solutions["raw_cstar_m_s"]["mixture_ratio"],
                                    "OF_difference": lpa.mixture_ratio-solutions["raw_cstar_m_s"]["mixture_ratio"],
                                    "LPA_raw_cstar_m_s": lp["raw_cstar_m_s"],
                                    "raw_cstar_objective_gap_m_s": solutions["raw_cstar_m_s"]["objective_value"]-lp["raw_cstar_m_s"],
                                    "LPA_source": lpa.source, "LPA_objective": lpa.objective,
                                    "LPA_metadata_cstar_m_s": lpa.ideal_cstar_m_s,
                                    "LPA_metadata_vacuum_isp_s": lpa.vacuum_isp_s})
                detailed.append({"case": base, "bounds": [lower, upper], "solutions": solutions,
                                 "LPA_optimizer": asdict(lpa), "evaluations": len(cache),
                                 "max_raw_vs_selected_cstar_difference_m_s": max(abs(p["raw_cstar_m_s"]-p["selected_cstar_m_s"]) for p in cache.values()),
                                 "max_injector_vs_throat_direct_relative_error": max(abs(p["injector_cstar_m_s"]-p["direct_throat_massflux_cstar_m_s"])/p["injector_cstar_m_s"] for p in cache.values())})
                print(f"{propellant} Pc={pc:g} eps={eps:g} {mode_name}: "
                      + ", ".join(f"max {m}: OF {s['mixture_ratio']:.7f}, value {s['objective_value']:.7f}" for m,s in solutions.items()), flush=True)
    provenance["elapsed_seconds"] = time.perf_counter()-began
    write_csv(output/"cea_objective_optima.csv", optima)
    write_csv(output/"cea_isp_penalties.csv", penalties)
    write_csv(output/"cea_lpa_optimizer_comparison.csv", comparisons)
    write_csv(output/"cea_grid_points.csv", grids)
    (output/"cea_comparison_results.json").write_text(json.dumps(strict_json({"provenance": provenance, "cases": detailed,
                                                              "optima": optima, "isp_penalties": penalties,
                                                              "lpa_optimizer_comparison": comparisons}), indent=2, allow_nan=False), encoding="utf-8")
    print(f"Saved {len(detailed)} cases, {len(grids)} grid points in {output}; elapsed {provenance['elapsed_seconds']:.3f}s", flush=True)


if __name__ == "__main__":
    main()

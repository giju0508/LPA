"""RocketCEA names and deterministic fallback properties for LPA propellants."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Coolant, Fuel, Oxidizer


@dataclass(frozen=True, slots=True)
class PropellantSpec:
    display_name: str
    cea_name: str
    phase: str
    kind: str
    water_mass_fraction: float = 0.0
    registration_card: str | None = None


def _h2o2_card(concentration: int) -> str:
    water = 100 - concentration
    return (
        f"oxid LPA_H2O2_{concentration} H 2 O 2 wt%={concentration:.1f} "
        f"t(k)=298.15 h,kj/mol=-187.78\n"
        f"oxid WATER H 2 O 1 wt%={water:.1f} t(k)=298.15 h,kj/mol=-285.83"
    )


def _ethanol_card(concentration: int) -> str:
    water = 100 - concentration
    return (
        f"fuel LPA_ETHANOL_{concentration} C 2 H 6 O 1 wt%={concentration:.1f} "
        f"t(k)=298.15 h,kj/mol=-277.69\n"
        f"fuel WATER H 2 O 1 wt%={water:.1f} t(k)=298.15 h,kj/mol=-285.83"
    )


OXIDIZERS: dict[Oxidizer, PropellantSpec] = {
    Oxidizer.LOX: PropellantSpec("LOX", "LOX", "liquid", "oxidizer"),
    Oxidizer.GOX: PropellantSpec("GOX", "GOX", "gas", "oxidizer"),
    Oxidizer.H2O2_70: PropellantSpec(
        "H2O2 (70%)", "LPA_H2O2_70", "liquid", "oxidizer", 0.30, _h2o2_card(70)
    ),
    Oxidizer.H2O2_80: PropellantSpec(
        "H2O2 (80%)", "LPA_H2O2_80", "liquid", "oxidizer", 0.20, _h2o2_card(80)
    ),
    Oxidizer.H2O2_90: PropellantSpec(
        "H2O2 (90%)", "LPA_H2O2_90", "liquid", "oxidizer", 0.10, _h2o2_card(90)
    ),
    Oxidizer.H2O2_100: PropellantSpec("H2O2 (100%)", "H2O2", "liquid", "oxidizer"),
    Oxidizer.N2O: PropellantSpec("N2O", "N2O", "liquid", "oxidizer"),
}


FUELS: dict[Fuel, PropellantSpec] = {
    Fuel.ETHANOL_70: PropellantSpec(
        "Ethanol (70%)", "LPA_ETHANOL_70", "liquid", "fuel", 0.30, _ethanol_card(70)
    ),
    Fuel.ETHANOL_80: PropellantSpec(
        "Ethanol (80%)", "LPA_ETHANOL_80", "liquid", "fuel", 0.20, _ethanol_card(80)
    ),
    Fuel.ETHANOL_90: PropellantSpec(
        "Ethanol (90%)", "LPA_ETHANOL_90", "liquid", "fuel", 0.10, _ethanol_card(90)
    ),
    Fuel.ETHANOL_100: PropellantSpec("Ethanol (100%)", "Ethanol", "liquid", "fuel"),
    Fuel.RP1: PropellantSpec("RP-1", "RP-1", "liquid", "fuel"),
    Fuel.JET_A1: PropellantSpec("Jet A-1", "JetA", "liquid", "fuel"),
    Fuel.LCH4: PropellantSpec("LCH4", "CH4", "liquid", "fuel"),
    Fuel.GCH4: PropellantSpec("GCH4", "GCH4", "gas", "fuel"),
    Fuel.LH2: PropellantSpec("LH2", "LH2", "liquid", "fuel"),
    Fuel.GH2: PropellantSpec("GH2", "GH2", "gas", "fuel"),
    Fuel.PROPANE: PropellantSpec("Propane", "C3H8", "gas", "fuel"),
}


COOLANT_CEA_NAMES: dict[Coolant, str] = {
    **{Coolant[item.name]: spec.cea_name for item, spec in OXIDIZERS.items()},
    **{Coolant[item.name]: spec.cea_name for item, spec in FUELS.items()},
    Coolant.WATER: "H2O",
}


@dataclass(frozen=True, slots=True)
class FallbackChemistry:
    optimum_mixture_ratio: float
    flame_temperature_k: float
    gamma: float
    molecular_weight_kg_kmol: float


_FUEL_CHEMISTRY: dict[Fuel, tuple[float, float, float]] = {
    Fuel.ETHANOL_70: (1.55, 3150.0, 23.5),
    Fuel.ETHANOL_80: (1.65, 3250.0, 23.0),
    Fuel.ETHANOL_90: (1.75, 3350.0, 22.5),
    Fuel.ETHANOL_100: (1.90, 3450.0, 22.0),
    Fuel.RP1: (2.65, 3650.0, 23.0),
    Fuel.JET_A1: (2.60, 3600.0, 23.5),
    Fuel.LCH4: (3.45, 3550.0, 20.5),
    Fuel.GCH4: (3.45, 3550.0, 20.5),
    Fuel.LH2: (5.50, 3500.0, 14.5),
    Fuel.GH2: (5.50, 3500.0, 14.5),
    Fuel.PROPANE: (3.05, 3600.0, 22.0),
}


_OXIDIZER_FACTOR: dict[Oxidizer, tuple[float, float, float]] = {
    Oxidizer.LOX: (1.0, 1.0, 0.0),
    Oxidizer.GOX: (1.0, 0.99, 0.0),
    Oxidizer.H2O2_70: (0.42, 0.78, 3.5),
    Oxidizer.H2O2_80: (0.52, 0.84, 2.8),
    Oxidizer.H2O2_90: (0.63, 0.91, 1.8),
    Oxidizer.H2O2_100: (0.72, 0.96, 1.0),
    Oxidizer.N2O: (0.72, 0.90, 2.0),
}


def fallback_chemistry(oxidizer: Oxidizer, fuel: Fuel, mixture_ratio: float) -> FallbackChemistry:
    """Return smooth engineering estimates when RocketCEA is unavailable.

    These values are intentionally conservative and are marked as fallback in
    every result.  They keep project editing, geometry and sweep workflows usable;
    they are not a substitute for a CEA solution in a released design report.
    """

    base_mr, base_temperature, base_mw = _FUEL_CHEMISTRY[fuel]
    mr_factor, temperature_factor, mw_add = _OXIDIZER_FACTOR[oxidizer]
    optimum = base_mr * mr_factor
    ratio = mixture_ratio / max(optimum, 1e-9)
    off_optimum = min(0.32, 0.16 * abs(ratio - 1.0) ** 1.25)
    temperature = base_temperature * temperature_factor * (1.0 - off_optimum)
    molecular_weight = base_mw + mw_add + min(4.0, 1.5 * abs(ratio - 1.0))
    gamma = max(1.12, min(1.28, 1.235 - 0.0032 * (molecular_weight - 18.0)))
    return FallbackChemistry(optimum, temperature, gamma, molecular_weight)


def rocketcea_names(oxidizer: Oxidizer, fuel: Fuel) -> tuple[str, str]:
    return OXIDIZERS[oxidizer].cea_name, FUELS[fuel].cea_name


def registration_cards(oxidizer: Oxidizer, fuel: Fuel) -> tuple[tuple[str, str, str], ...]:
    """Return ``(kind, name, card)`` records needed before CEA object creation."""

    records: list[tuple[str, str, str]] = []
    for spec in (OXIDIZERS[oxidizer], FUELS[fuel]):
        if spec.registration_card:
            records.append((spec.kind, spec.cea_name, spec.registration_card))
    return tuple(records)

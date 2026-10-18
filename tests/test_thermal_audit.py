from __future__ import annotations

import pytest

from lpa.thermal import bartz_heat_transfer_coefficient
from tools.thermal_audit import independent_bartz


def test_independent_bartz_matches_production_equation() -> None:
    values = {
        "chamber_pressure_pa": 1.0e6,
        "characteristic_velocity_m_s": 1845.611,
        "throat_diameter_m": 0.03179,
        "throat_radius_of_curvature_m": 0.00607189,
        "area_ratio": 1.0,
        "wall_temperature_k": 582.2,
        "stagnation_temperature_k": 3123.079,
        "mach": 1.0,
        "viscosity_pa_s": 7.86006e-5,
        "specific_heat_j_kgk": 2615.622,
        "prandtl": 0.720031,
        "gamma": 1.198297,
    }

    independent = independent_bartz(**values)
    production = bartz_heat_transfer_coefficient(**values)

    assert independent["coefficient_w_m2k"] == pytest.approx(
        production, rel=1.0e-13
    )
    assert independent["convective_flux_w_m2"] > 0.0


@pytest.mark.parametrize(
    ("name", "expected_exponent"),
    (
        ("chamber_pressure_pa", 0.8),
        ("characteristic_velocity_m_s", -0.8),
        ("viscosity_pa_s", 0.2),
        ("specific_heat_j_kgk", 1.0),
        ("area_ratio", -0.9),
        ("throat_radius_of_curvature_m", -0.1),
    ),
)
def test_independent_bartz_power_law_sensitivity(
    name: str, expected_exponent: float
) -> None:
    values = {
        "chamber_pressure_pa": 1.0e6,
        "characteristic_velocity_m_s": 1800.0,
        "throat_diameter_m": 0.03,
        "throat_radius_of_curvature_m": 0.006,
        "area_ratio": 1.0,
        "wall_temperature_k": 600.0,
        "stagnation_temperature_k": 3100.0,
        "mach": 1.0,
        "viscosity_pa_s": 8.0e-5,
        "specific_heat_j_kgk": 2600.0,
        "prandtl": 0.72,
        "gamma": 1.20,
    }
    base = independent_bartz(**values)["coefficient_w_m2k"]
    perturbed = dict(values)
    perturbed[name] *= 1.1
    ratio = independent_bartz(**perturbed)["coefficient_w_m2k"] / base

    assert ratio == pytest.approx(1.1**expected_exponent, rel=1.0e-13)

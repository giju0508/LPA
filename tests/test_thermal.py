from __future__ import annotations

from math import isfinite

import pytest

from lpa.core.models import Resolution
from lpa.thermal import (
    MATERIALS,
    MESH_SECTION_COUNTS,
    SegmentValidationError,
    ThermalSolverSettings,
    adiabatic_wall_temperature,
    analyze_thermal,
    bartz_heat_transfer_coefficient,
    dittus_boelter_nusselt,
    film_effectiveness,
    get_material,
    gnielinski_nusselt,
    internal_flow_heat_transfer,
    material_reference_metadata,
    mesh_section_count,
    radiative_heat_flux,
    validate_segments,
)


@pytest.fixture
def contour() -> dict[str, object]:
    return {
        "x_m": (0.0, 0.08, 0.12, 0.24),
        "radius_m": (0.040, 0.040, 0.015, 0.030),
        "area_m2": (
            0.005026548,
            0.005026548,
            0.000706858,
            0.002827433,
        ),
        "throat_index": 2,
        "chamber_end_index": 1,
        "throat_x_m": 0.12,
        "metadata": {"Rn/Rt": 0.382},
    }


@pytest.fixture
def gas() -> dict[str, object]:
    return {
        "x_m": (0.0, 0.08, 0.12, 0.24),
        "pressure_pa": (2.0e6, 1.95e6, 1.10e6, 0.08e6),
        "temperature_k": (3400.0, 3370.0, 3050.0, 1850.0),
        "specific_heat_j_kgk": (3100.0, 3100.0, 3050.0, 2850.0),
        "gamma": (1.22, 1.22, 1.22, 1.24),
        "mach": (0.08, 0.15, 1.0, 3.0),
        "mass_flux_kg_m2_s": (180.0, 180.0, 1333.333, 330.0),
        "viscosity_pa_s": (8.8e-5, 8.7e-5, 8.2e-5, 6.2e-5),
        "prandtl": (0.70, 0.70, 0.70, 0.72),
        "source": "test-gas",
    }


def coolant() -> dict[str, float | str]:
    return {
        "coolant": "H2O",
        "inlet_pressure_bar": 30.0,
        "inlet_temperature_k": 290.0,
        "relative_mass_flow_percent": 25.0,
    }


def regen(
    identifier: str = "regen",
    start: float | str = "top",
    end: float | str = "bottom",
    *,
    coolant_definition: dict[str, float | str] | None = None,
    inherit: str | None = None,
    coating: bool = True,
) -> dict[str, object]:
    segment: dict[str, object] = {
        "type": "regen",
        "segment_id": identifier,
        "location": {"start": start, "end": end},
        "wall_thickness_mm": 1.0,
        "channel_height_mm": (1.5, 0.8, 1.5),
        "channel_count": 48,
        "material": "CuCrZr",
        "width_mode": "channel_width",
        "widths_mm": (1.0, 0.55, 1.0),
        "coflow": False,
    }
    if coolant_definition is not None:
        segment["coolant"] = coolant_definition
    if inherit is not None:
        segment["inherit_coolant_from"] = inherit
    if coating:
        segment["coating"] = {
            "conductivity_w_mk": 1.5,
            "thickness_mm": 0.05,
        }
    return segment


def low_settings(**overrides: object) -> ThermalSolverSettings:
    values: dict[str, object] = {
        "resolution": "low",
        "chamber_pressure_pa": 2.0e6,
        "stagnation_temperature_k": 3400.0,
        "characteristic_velocity_m_s": 1500.0,
        "total_mass_flow_kg_s": 0.95,
        "gas_emissivity": 0.05,
    }
    values.update(overrides)
    return ThermalSolverSettings(**values)


def test_mesh_levels_are_explicit_and_match_core_model() -> None:
    assert MESH_SECTION_COUNTS == {"low": 120, "medium": 300, "high": 700}
    assert mesh_section_count(Resolution.LOW) == 120
    assert mesh_section_count("MEDIUM") == 300
    assert mesh_section_count(Resolution.HIGH) == 700


def test_material_tables_are_temperature_dependent_and_referenced() -> None:
    assert set(MATERIALS) == {"CuCrZr", "IN625", "IN718", "AlSi10Mg", "C103", "Ti64"}
    for name in MATERIALS:
        material = get_material(name)
        low, high = material.valid_temperature_range_k
        midpoint = 0.5 * (low + high)
        value = material.conductivity(midpoint)
        assert value > 0
        assert min(material.conductivity_w_mk) <= value <= max(material.conductivity_w_mk)
        assert material.reference.identifier
        assert material.reference.url.startswith("https://")
    metadata = material_reference_metadata()
    assert "LPBF" in metadata["CuCrZr"]["manufacturing_condition"]
    assert metadata["IN625"]["identifier"] == "SMC-063"


def test_bartz_recovery_and_area_scaling() -> None:
    recovery = adiabatic_wall_temperature(3500.0, 2.5, 1.22, 0.70)
    assert 2500.0 < recovery < 3500.0
    common = {
        "chamber_pressure_pa": 2.0e6,
        "characteristic_velocity_m_s": 1550.0,
        "throat_diameter_m": 0.030,
        "throat_radius_of_curvature_m": 0.00573,
        "wall_temperature_k": 800.0,
        "stagnation_temperature_k": 3500.0,
        "mach": 1.0,
        "viscosity_pa_s": 8.0e-5,
        "specific_heat_j_kgk": 3000.0,
        "prandtl": 0.70,
        "gamma": 1.22,
    }
    throat = bartz_heat_transfer_coefficient(area_ratio=1.0, **common)
    expanded = bartz_heat_transfer_coefficient(area_ratio=8.0, **common)
    assert throat > 5_000.0
    assert 0 < expanded < throat


def test_internal_flow_correlations_cover_laminar_transition_and_turbulent() -> None:
    assert gnielinski_nusselt(1000.0, 5.0) == pytest.approx(3.66)
    assert gnielinski_nusselt(50_000.0, 5.0) > 100.0
    assert dittus_boelter_nusselt(50_000.0, 5.0) > 100.0
    result = internal_flow_heat_transfer(
        mass_flow_kg_s=0.2,
        total_flow_area_m2=1.0e-4,
        hydraulic_diameter_m=1.0e-3,
        density_kg_m3=900.0,
        viscosity_pa_s=8.0e-4,
        conductivity_w_mk=0.3,
        specific_heat_j_kgk=3000.0,
    )
    assert result.coefficient_w_m2k > 1_000.0
    assert result.reynolds > 2_300.0


def test_film_effectiveness_is_bounded_and_decays_downstream() -> None:
    ahead = film_effectiveness(-0.001, 0.03, 0.001)
    injection = film_effectiveness(0.0, 0.03, 0.001)
    near = film_effectiveness(0.01, 0.03, 0.001)
    far = film_effectiveness(0.05, 0.03, 0.001)
    assert ahead == 0.0
    assert injection == pytest.approx(1.0)
    assert 0.0 < far < near < injection


def test_regen_solver_returns_rpa_temperature_arrays_and_coolant_rise(
    contour: dict[str, object], gas: dict[str, object]
) -> None:
    result = analyze_thermal(
        contour,
        gas,
        [regen(coolant_definition=coolant())],
        low_settings(),
    )
    assert result.section_count == 120
    assert result.station_count == 120
    assert len(result.Twg) == len(result.Twi) == len(result.Twc) == len(result.Tc) == 120
    assert result.converged
    assert all(isfinite(value) for value in result.Twg)
    for Twg, Twi, Twc, Tc in zip(result.Twg, result.Twi, result.Twc, result.Tc):
        assert Twg >= Twi >= Twc >= Tc
    assert result.coolant_inlet_temperature_k["regen"] == pytest.approx(290.0)
    assert result.coolant_outlet_temperature_k["regen"] > 290.0
    assert result.coolant_inlet_pressure_bar["regen"] == pytest.approx(30.0)
    assert 0.0 < result.coolant_outlet_pressure_bar["regen"] < 30.0
    assert result.coolant_pressure_drop_bar["regen"] == pytest.approx(
        result.coolant_inlet_pressure_bar["regen"]
        - result.coolant_outlet_pressure_bar["regen"]
    )
    assert result.metadata["coolant_pressure_model"].startswith("Darcy-Weisbach")
    assert max(result.gas_coefficient_w_m2k) > 1_000.0
    assert max(result.coolant_coefficient_w_m2k) > 1_000.0


def test_regen_axial_coolant_state_and_occupied_angle_geometry_are_reported(
    contour: dict[str, object], gas: dict[str, object]
) -> None:
    segment = regen(coolant_definition=coolant(), coating=False)
    segment.pop("widths_mm")
    segment["width_mode"] = "channel_angle"
    segment["channel_angle_deg"] = 4.0

    result = analyze_thermal(contour, gas, [segment], low_settings())

    assert len(result.coolant_pressure_bar) == result.section_count
    assert len(result.coolant_velocity_m_s) == result.section_count
    assert len(result.coolant_density_kg_m3) == result.section_count
    assert all(isfinite(value) for value in result.coolant_pressure_bar)
    assert all(value > 0.0 for value in result.coolant_velocity_m_s)
    assert all(value > 0.0 for value in result.coolant_density_kg_m3)
    # Default coolant direction is opposite the gas direction, so the nozzle
    # end of a full-length segment is the coolant inlet.
    assert result.coolant_pressure_bar[-1] == pytest.approx(30.0)
    assert result.coolant_pressure_bar[0] < result.coolant_pressure_bar[-1]

    geometry = result.metadata["angle_channel_geometry_by_segment"]["regen"]
    assert geometry["channel_width_mm"] == pytest.approx(
        tuple(radius_mm * 4.0 * 3.141592653589793 / 180.0 for radius_mm in (40.0, 15.0, 30.0))
    )
    expected_ribs = tuple(
        2.0 * 3.141592653589793 * radius_mm / 48.0 - channel_width
        for radius_mm, channel_width in zip(
            (40.0, 15.0, 30.0), geometry["channel_width_mm"]
        )
    )
    assert geometry["rib_width_mm"] == pytest.approx(expected_ribs)


def test_regen_coolant_link_inherits_source_outlet(
    contour: dict[str, object], gas: dict[str, object]
) -> None:
    downstream = regen(
        "downstream", 120.0, "bottom", coolant_definition=coolant(), coating=False
    )
    upstream = regen("upstream", "top", 120.0, inherit="downstream", coating=False)
    result = analyze_thermal(
        contour, gas, [upstream, downstream], low_settings(gas_emissivity=0.0)
    )
    assert result.linked_coolant_source == {"upstream": "downstream"}
    assert result.coolant_inlet_temperature_k["upstream"] == pytest.approx(
        result.coolant_outlet_temperature_k["downstream"]
    )
    assert result.coolant_inlet_pressure_bar["upstream"] == pytest.approx(
        result.coolant_outlet_pressure_bar["downstream"]
    )
    assert result.coolant_outlet_temperature_k["upstream"] > result.coolant_inlet_temperature_k["upstream"]
    assert result.metadata["coolant_identity_by_segment"] == {
        "upstream": "H2O",
        "downstream": "H2O",
    }


def test_independent_regen_circuits_keep_their_own_inlet_pressures(
    contour: dict[str, object], gas: dict[str, object]
) -> None:
    first_coolant = coolant()
    first_coolant["inlet_pressure_bar"] = 32.0
    second_coolant = coolant()
    second_coolant["inlet_pressure_bar"] = 45.0
    result = analyze_thermal(
        contour,
        gas,
        [
            regen("first", "top", 120.0, coolant_definition=first_coolant),
            regen("second", 120.0, "bottom", coolant_definition=second_coolant),
        ],
        low_settings(),
    )

    assert result.coolant_inlet_pressure_bar == pytest.approx(
        {"first": 32.0, "second": 45.0}
    )
    assert result.coolant_outlet_pressure_bar["first"] < 32.0
    assert result.coolant_outlet_pressure_bar["second"] < 45.0
    assert set(result.coolant_pressure_drop_bar) == {"first", "second"}


def test_unresolved_link_is_reported_and_segment_is_inactive(
    contour: dict[str, object], gas: dict[str, object]
) -> None:
    broken = regen("broken", inherit="deleted-segment")
    report = validate_segments([broken], contour)
    assert report.is_valid
    assert report.warnings[0].code == "unresolved_regen_link"
    result = analyze_thermal(contour, gas, [broken], low_settings())
    assert "broken" in result.metadata["inactive_segment_ids"]
    assert all(identifier is None for identifier in result.active_segment_id)
    assert any("inactive" in warning for warning in result.warnings)


def test_regen_and_radiation_overlap_is_rejected(
    contour: dict[str, object], gas: dict[str, object]
) -> None:
    regen_segment = regen("regen", 0.0, 160.0, coolant_definition=coolant())
    radiation = {
        "type": "radiation",
        "segment_id": "radiation",
        "location": {"start": 120.0, "end": "bottom"},
        "wall_thickness_mm": 1.0,
        "material": "C103",
        "emissivity": 0.8,
    }
    report = validate_segments([regen_segment, radiation], contour)
    assert any(issue.code == "regen_radiation_overlap" for issue in report.errors)
    with pytest.raises(SegmentValidationError, match="overlaps"):
        analyze_thermal(contour, gas, [regen_segment, radiation], low_settings())


def test_radiation_balance_and_tbc_temperature_drop(
    contour: dict[str, object], gas: dict[str, object]
) -> None:
    radiation = {
        "type": "radiation",
        "segment_id": "radiation",
        "location": {"start": "top", "end": "bottom"},
        "wall_thickness_mm": 0.8,
        "material": "C103",
        "emissivity": 0.8,
        "coating": {"conductivity_w_mk": 1.5, "thickness_mm": 0.05},
    }
    settings = low_settings(gas_emissivity=0.0, ambient_temperature_k=295.0)
    result = analyze_thermal(contour, gas, [radiation], settings)
    index = result.Twc.index(max(result.Twc))
    assert result.Twg[index] > result.Twi[index] > result.Twc[index] > 295.0
    external = radiative_heat_flux(result.Twc[index], 295.0, 0.8)
    assert result.heat_flux_w_m2[index] == pytest.approx(external, rel=2.0e-4)
    assert result.converged


def test_film_segment_reduces_regen_hot_wall_temperature(
    contour: dict[str, object], gas: dict[str, object]
) -> None:
    regen_segment = regen(coolant_definition=coolant(), coating=False)
    baseline = analyze_thermal(contour, gas, [regen_segment], low_settings())
    film = {
        "type": "film",
        "segment_id": "film",
        "coolant": "H2O",
        "coolant_temperature_k": 300.0,
        "relative_mass_flow_percent": 3.0,
        "injection_location_mm": 80.0,
    }
    cooled = analyze_thermal(contour, gas, [regen_segment, film], low_settings())
    index = min(range(len(cooled.x_m)), key=lambda item: abs(cooled.x_m[item] - 0.08))
    assert cooled.film_effectiveness[index] > 0.9
    assert cooled.Twg[index] < baseline.Twg[index]

"""Backend automatic-O/F integration, including an analytic feed response."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

import lpa.analysis as analysis
from lpa.analysis import AnalysisService
from lpa.ui.input_views import default_segment


def project_fixture():
    return {
        "engine": {"engine_name": "Automatic O/F service regression", "chamber_pressure_bar": "20",
                   "mixture_ratio": "9", "mixture_ratio_auto": True,
                   "oxidizer": "LOX", "fuel": "Ethanol", "fuel_mass_fraction_pct": "70"},
        "thrust_chamber": {
            "contraction_mode": "Contraction area ratio", "contraction_area_ratio": "6.25",
            "exit_condition_mode": "Expansion area ratio", "exit_condition_value": "5",
            "flow_model": "Shifting equilibrium", "reaction_efficiency_pct": "98",
            "nozzle_efficiency_mode": "Estimate", "throttle_enabled": False, "ambient_enabled": False,
            "sizing_mode": "Engine nominal thrust", "nominal_thrust": "2000", "thrust_unit": "N",
            "nominal_thrust_ambient_atm": "1", "chamber_length_mode": "Characteristic length",
            "characteristic_length_mm": "1200", "contraction_angle_deg": "45", "r2_ratio": "0.5",
            "r1_rt": "1.5", "nozzle_type": "Conical", "nozzle_half_angle_deg": "15", "rn_rt": "0.382"},
        "thermal": {"thermal_enabled": False, "thermal_resolution": "Low", "thermal_max_iterations": "200",
                    "regen_feed_feedback_enabled": False, "segments": []},
    }


def test_backend_uses_automatic_objective_and_preserves_user_snapshot():
    project = project_fixture()
    original = copy.deepcopy(project)
    result = AnalysisService().analyze(project)
    optimum = result["mixture_ratio_optimization"]
    assert optimum["enabled"] and optimum["source"] == "rocketcea"
    assert optimum["objective"] == "maximum theoretical vacuum specific impulse"
    assert optimum["mixture_ratio"] == pytest.approx(1.313420882, abs=2e-5)
    assert optimum["vacuum_isp_s"] == pytest.approx(278.718641352, abs=2e-5)
    assert result["performance"]["mixture_ratio"] == pytest.approx(optimum["mixture_ratio"])
    assert project == result["input_project"] == original


def test_automatic_mode_ignores_inactive_manual_of_but_manual_mode_validates_it():
    project = project_fixture()
    project["engine"]["mixture_ratio"] = "inactive malformed manual value"
    result = AnalysisService().analyze(project)
    assert result["performance"]["mixture_ratio"] == pytest.approx(1.313420882, abs=2e-5)
    assert result["input_project"]["engine"]["mixture_ratio"] == project["engine"]["mixture_ratio"]
    project["engine"]["mixture_ratio_auto"] = False
    with pytest.raises(ValueError):
        AnalysisService().analyze(project)


def test_manual_of_is_retained_when_automatic_mode_is_disabled():
    project = project_fixture()
    project["engine"].update(mixture_ratio="1.1", mixture_ratio_auto=False)
    result = AnalysisService().analyze(project)
    assert result["performance"]["mixture_ratio"] == pytest.approx(1.1)
    assert result["mixture_ratio_optimization"] == {"enabled": False}


def test_feed_feedback_reoptimizes_and_uses_selected_of_for_coolant_flow(monkeypatch):
    # Real CEA/performance; the thermal outlet is an explicit analytic stub.
    # This checks state/flow wiring, not heat-transfer accuracy.
    project = project_fixture()
    project["engine"].update(fuel_temperature_k="300", fuel_pressure_bar="250")
    regen = default_segment("Regen", 1)
    regen.update(id="fuel", coolant_source_mode="Engine fuel",
                 coolant_inlet_temperature_k="300", coolant_inlet_pressure_bar="250")
    project["thermal"].update(thermal_enabled=True, regen_feed_feedback_enabled=True, segments=[regen])
    original = copy.deepcopy(project)
    searches = []
    flows = []
    optimize = analysis.optimize_mixture_ratio_for_inputs
    analyze_engine = analysis.analyze_engine

    def traced_search(inputs, **kwargs):
        optimum = optimize(inputs, **kwargs)
        searches.append((inputs.engine.fuel_temperature_k, optimum.mixture_ratio))
        return optimum

    def traced_engine(inputs, **kwargs):
        result = analyze_engine(inputs, **kwargs)
        coolant = result.inputs.thermal.segments[0].coolant
        assert coolant.relative_mass_flow_percent == pytest.approx(100 / (1 + result.inputs.engine.mixture_ratio))
        return result

    def analytic_outlet(contour, gas, segments, **kwargs):
        flows.append(segments[0]["coolant"]["relative_mass_flow_percent"])
        values = {"converged": True, "physical_validity": "valid", "warnings": [], "metadata": {},
                  "coolant_outlet_temperature_k": {"fuel": 305.0},
                  "coolant_outlet_pressure_bar": {"fuel": 249.0}}
        return SimpleNamespace(**values, x_m=(), Tc_K=(), active_segment_id=(),
                               as_dict=lambda: copy.deepcopy(values))

    monkeypatch.setattr(analysis, "optimize_mixture_ratio_for_inputs", traced_search)
    monkeypatch.setattr(analysis, "analyze_engine", traced_engine)
    monkeypatch.setattr("lpa.thermal.analyze_thermal", analytic_outlet)
    result = AnalysisService().analyze(project)
    assert result["regen_feed_feedback"]["converged"]
    assert len(searches) == len(flows) >= 3
    assert abs(searches[-1][1] - searches[0][1]) > 1e-5
    assert searches[-1][0] == pytest.approx(305, abs=.06)
    for (_, selected_mr), fraction in zip(searches, flows):
        assert fraction == pytest.approx(100 / (1 + selected_mr))
    assert result["mixture_ratio_optimization"]["mixture_ratio"] == pytest.approx(searches[-1][1])
    assert result["input_project"] == project == original

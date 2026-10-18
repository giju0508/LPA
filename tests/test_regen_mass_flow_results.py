from __future__ import annotations

import pytest

from lpa.analysis import _external_regen_coolant_flows
from lpa.core import Coolant, CoolantDefinition


def test_regen_coolant_relative_mass_flow_has_no_upper_limit() -> None:
    definition = CoolantDefinition(Coolant.WATER, 35.0, 293.15, 175.0)

    assert definition.relative_mass_flow_percent == pytest.approx(175.0)
    with pytest.raises(ValueError, match="finite and positive"):
        CoolantDefinition(Coolant.WATER, 35.0, 293.15, 0.0)


def test_external_regen_coolant_flows_report_each_independent_custom_circuit() -> None:
    project = {
        "thermal": {
            "thermal_enabled": True,
            "segments": [
                {
                    "type": "Regen",
                    "id": "water-root",
                    "name": "Water circuit",
                    "coolant_source_mode": "Custom coolant",
                    "coolant": "H2O",
                    "relative_mass_flow_pct": "150",
                },
                {
                    "type": "Regen",
                    "id": "water-linked",
                    "name": "Water circuit downstream",
                    "coolant_source_mode": "Receive from Regen segment",
                    "coolant_source_id": "water-root",
                },
                {
                    "type": "Regen",
                    "id": "fuel-circuit",
                    "name": "Fuel circuit",
                    "coolant_source_mode": "Engine fuel",
                    "relative_mass_flow_pct": "40",
                },
            ],
        }
    }

    assert _external_regen_coolant_flows(project, 2.0) == [
        {
            "segment_id": "water-root",
            "segment_name": "Water circuit",
            "coolant": "H2O",
            "relative_mass_flow_percent": 150.0,
            "kg_s": 3.0,
        }
    ]


def test_external_regen_coolant_flows_are_inactive_when_thermal_analysis_is_off() -> None:
    project = {
        "thermal": {
            "thermal_enabled": False,
            "segments": [
                {
                    "type": "Regen",
                    "coolant_source_mode": "Custom coolant",
                    "coolant": "H2O",
                    "relative_mass_flow_pct": "150",
                }
            ],
        }
    }

    assert _external_regen_coolant_flows(project, 2.0) == []

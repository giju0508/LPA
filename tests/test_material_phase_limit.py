"""Sourced solid-wall consistency checks, independent of conductivity bounds."""
from dataclasses import replace
from math import inf, nan

import pytest

from lpa.thermal.materials import (
    MATERIALS,
    get_material,
    material_phase_limit_issue,
    material_reference_metadata,
)


def test_cucrzr_melting_reference_is_supplier_nominal_value_not_conductivity_limit():
    material = get_material("CuCrZr")
    assert material.melting_temperature_k == pytest.approx(1354.15)
    assert material.valid_temperature_range_k == pytest.approx((293.15, 973.15))
    assert material.melting_reference is not None
    assert material.melting_reference.authors_or_organization == "Aurubis Stolberg"
    assert "EN_2026_01" in material.melting_reference.identifier
    assert "does not qualify the LPBF" in material.melting_reference.notes
    assert "allowable service temperature" in material.melting_reference.notes
    assert material.reference != material.melting_reference


def test_limit_check_warns_at_and_above_melting_but_does_not_change_conductivity():
    material = get_material("CuCr1Zr")
    assert material_phase_limit_issue("CuCrZr", 1000.) is None
    for temperature in (1354.15, 1492.91):
        issue = material_phase_limit_issue("CuCr1Zr", temperature)
        assert issue is not None
        assert "solid-wall assumption invalid" in issue
        assert "1354.15 K" in issue
        assert "Melting, ablation" in issue
        assert material.conductivity(temperature) == material.conductivity_w_mk[-1]


def test_other_materials_have_no_unsourced_melting_limits():
    for name, material in MATERIALS.items():
        if name != "CuCrZr":
            assert material.melting_temperature_k is None
            assert material.melting_reference is None
            assert material_phase_limit_issue(name, 3000.) is None


def test_metadata_preserves_independent_provenance_and_unknown_limits():
    metadata = material_reference_metadata()
    copper = metadata["CuCrZr"]
    assert copper["melting_temperature_k"] == pytest.approx(1354.15)
    assert copper["melting_reference"]["year"] == 2026
    assert "aurubis.com" in copper["melting_reference"]["url"]
    assert "10.1016/j.matchar.2024.114103" in copper["url"]
    assert metadata["IN718"]["melting_temperature_k"] is None
    assert metadata["IN718"]["melting_reference"] is None


@pytest.mark.parametrize("temperature", [0., -1., nan, inf])
def test_invalid_temperature_rejected_even_without_sourced_limit(temperature):
    with pytest.raises(ValueError, match="finite and positive"):
        material_phase_limit_issue("CuCrZr", temperature)
    with pytest.raises(ValueError, match="finite and positive"):
        material_phase_limit_issue("IN718", temperature)


@pytest.mark.parametrize("temperature", [0., -1., nan, inf])
def test_material_rejects_invalid_melting_value(temperature):
    with pytest.raises(ValueError, match="melting temperature"):
        replace(get_material("CuCrZr"), melting_temperature_k=temperature)


def test_melting_source_and_temperature_must_be_paired():
    with pytest.raises(ValueError, match="source reference"):
        replace(get_material("CuCrZr"), melting_reference=None)
    with pytest.raises(ValueError, match="source reference"):
        replace(get_material("CuCrZr"), melting_temperature_k=None)

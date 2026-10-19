from dataclasses import replace

import pytest

from lpa.thermal import analyze_thermal
import lpa.thermal.solver as solver
from tests.test_release_thermal_fixes import cylinder,gas,regen,settings


@pytest.mark.parametrize("sampled_max,exceeded",[(1400.,True),(1300.,False)])
def test_sampled_solid_temperature_cannot_be_hidden_by_a_lower_cell_average(monkeypatch,sampled_max,exceeded):
    original=solver._solve_regen_station
    def sampled_wall(**kwargs):
        wall=original(**kwargs)
        return replace(wall,Twg=1200.,Twi=1200.,Twc=1190.,
            wall_temperature_min_k=1100.,wall_temperature_max_k=sampled_max,
            solid_temperature_max_k=sampled_max)
    monkeypatch.setattr(solver,"_solve_regen_station",sampled_wall)
    segment=regen();segment.pop("wall_conductivity_w_mk");segment["material"]="CuCrZr"
    result=analyze_thermal(cylinder(),gas(),[segment],settings())
    assessment=result.metadata["coolant_property_metadata"]["water"]["wall_material_assessment"]
    assert assessment["reference_melting_temperature_k"]==pytest.approx(1354.15)
    assert assessment["cells_above_reference_melting_point"]==(120 if exceeded else 0)
    assert assessment["maximum_sampled_base_wall_temperature_k"]==sampled_max
    warnings=[w for w in result.physical_issues if "solid-wall assumption invalid" in w]
    assert len(warnings)==int(exceeded)  # Aggregate once per circuit.
    if exceeded:
        assert result.physical_validity=="invalid"
        assert set(result.station_applicability)=={"invalid"}
        assert max(result.Twg)<assessment["reference_melting_temperature_k"]


def test_sampled_cold_wall_boiling_is_flagged_even_when_the_mean_is_subcooled(monkeypatch):
    original=solver._solve_regen_station
    def sampled_wall(**kwargs):
        wall=original(**kwargs)
        return replace(wall,Twg=450.,Twi=450.,Twc=400.,
                       coolant_wall_temperature_max_k=550.)
    monkeypatch.setattr(solver,"_solve_regen_station",sampled_wall)
    result=analyze_thermal(cylinder(),gas(),[regen()],settings())
    assert result.physical_validity=="unsupported"
    assert any("coolant-side wall exceeds saturation" in w for w in result.physical_issues)

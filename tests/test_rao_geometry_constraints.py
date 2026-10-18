from __future__ import annotations

from math import atan2, cos, degrees, isfinite, radians, sin, sqrt, tan
from random import Random

import pytest

from lpa.core.rao_geometry import constrain_rao_angles


def _assert_constructible(epsilon, fraction, radius, angles):
    """Independently construct the arc and tangent intersection at Rt=1."""

    initial, exit_angle = angles
    assert 0 <= exit_angle < initial < 90
    length = fraction * (
        (sqrt(epsilon) - 1) / tan(radians(15)) + radius * tan(radians(7.5))
    )
    # Translate the radial origin to the throat. Subtracting two radii near
    # Rt=1 would otherwise obscure tiny, but valid, control-polygon edges.
    end_r = sqrt(epsilon) - 1
    start_x = radius * sin(radians(initial))
    start_r = radius * (1 - cos(radians(initial)))
    initial_slope, exit_slope = tan(radians(initial)), tan(radians(exit_angle))
    control_x = (
        end_r - start_r + initial_slope * start_x - exit_slope * length
    ) / (initial_slope - exit_slope)
    control_r = end_r - exit_slope * (length - control_x)
    assert 0 < start_x < control_x < length
    assert 0 < start_r < control_r <= end_r
    actual = (
        degrees(atan2(control_r - start_r, control_x - start_x)),
        degrees(atan2(end_r - control_r, length - control_x)),
    )
    assert actual == pytest.approx(angles, abs=1e-8)
    # Positive control-polygon edges ensure no hidden fold between samples.
    for t in (0, 0.01, 0.25, 0.5, 0.75, 0.99, 1):
        assert (1 - t) * (control_x - start_x) + t * (length - control_x) > 0
        assert (1 - t) * (control_r - start_r) + t * (end_r - control_r) >= 0


@pytest.mark.parametrize("epsilon,fraction,radius,seed", [
    (14.0, 0.8, 0.382, (27.4, 9.8)),
    (100.0, 0.5, 1.0, (29.7, 11.4)),
    (14.0, 0.8, 0.382, (30.0, 0.0)),
])
def test_valid_candidates_remain_exactly_unchanged(epsilon, fraction, radius, seed):
    result = constrain_rao_angles(epsilon, fraction, radius, *seed)
    assert result == seed
    _assert_constructible(epsilon, fraction, radius, result)


def test_low_expansion_flow_candidates_project_before_tangent_intersection():
    result = constrain_rao_angles(2.0, 0.8, 0.382, 11.263, 10.137)
    assert result[0] > 11.263
    assert result[1] == 10.137
    _assert_constructible(2.0, 0.8, 0.382, result)


def test_very_low_expansion_can_use_small_projected_angles():
    result = constrain_rao_angles(1.0001, 0.8, 0.382, 0.001, 0.0009)
    assert 0.071 < result[0] < 0.928
    _assert_constructible(1.0001, 0.8, 0.382, result)


@pytest.mark.parametrize("seed", [(0.0, 0.0), (100.0, 100.0), (35.0, 30.0)])
def test_invalid_initial_or_exit_candidate_still_produces_exact_tangents(seed):
    result = constrain_rao_angles(14.0, 0.8, 0.382, *seed)
    assert all(isfinite(value) for value in result)
    _assert_constructible(14.0, 0.8, 0.382, result)


@pytest.mark.parametrize("epsilon,fraction,radius", [
    (1.1, 0.8, 0.382),
    (1.2, 0.5, 0.382),
    (1.0001, 0.8, 0.001),
    (4.0, 0.1, 0.5),
    ((1 + 0.382 * (1 - cos(radians(15)))) ** 2, 1.0, 0.382),
])
def test_impossible_dimensions_are_reported_without_changing_them(epsilon, fraction, radius):
    with pytest.raises(ValueError, match="nozzle length and throat radius.*Rn/Rt"):
        constrain_rao_angles(epsilon, fraction, radius, 30.0, 10.0)


@pytest.mark.parametrize("parameters", [
    (1.0, 0.8, 0.382, 30.0, 10.0),
    (float("nan"), 0.8, 0.382, 30.0, 10.0),
    (14.0, 0.0, 0.382, 30.0, 10.0),
    (14.0, float("inf"), 0.382, 30.0, 10.0),
    (14.0, 0.8, 0.0, 30.0, 10.0),
    (14.0, 0.8, float("nan"), 30.0, 10.0),
    (14.0, 0.8, 0.382, -1.0, 10.0),
    (14.0, 0.8, 0.382, 30.0, -1.0),
    (14.0, 0.8, 0.382, float("inf"), 10.0),
    (14.0, 0.8, 0.382, 30.0, float("nan")),
])
def test_nonfinite_or_invalid_inputs_are_rejected(parameters):
    with pytest.raises(ValueError, match="Rao"):
        constrain_rao_angles(*parameters)


def test_random_dimensions_match_an_independent_circle_feasibility_test():
    random = Random(20261008)
    accepted = rejected = 0
    for _ in range(320):
        epsilon = 1 + 10 ** random.uniform(-4, 3)
        radius = 10 ** random.uniform(-4, 1)
        fraction = random.uniform(0.5, 1.2)
        gain = sqrt(epsilon) - 1
        length = fraction * (gain / tan(radians(15)) + radius * tan(radians(7.5)))
        if gain < radius:
            feasible = length**2 + (gain - radius)**2 > radius**2
        else:
            feasible = length > radius
        seed = (random.uniform(0, 120), random.uniform(0, 80))
        if feasible:
            result = constrain_rao_angles(epsilon, fraction, radius, *seed)
            _assert_constructible(epsilon, fraction, radius, result)
            accepted += 1
        else:
            with pytest.raises(ValueError, match="nozzle length and throat radius"):
                constrain_rao_angles(epsilon, fraction, radius, *seed)
            rejected += 1
    assert accepted > 0 and rejected > 0

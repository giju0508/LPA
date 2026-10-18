from __future__ import annotations

import pytest

from lpa.core.rao import rao_angles


def test_rao_angles_match_published_sp125_worked_example():
    # NASA SP-125, printed p. 98, explicitly lists these two wall angles.
    assert rao_angles(14.0, 0.8) == pytest.approx((27.4, 9.8), abs=1e-12)


@pytest.mark.parametrize("expansion_ratio,length_fraction,expected", [
    (5.0, 0.6, (28.5, 20.0)),
    (5.0, 1.0, (20.0, 8.5)),
    (10.0, 0.8, (26.0, 10.5)),
    (20.0, 0.8, (29.0, 9.0)),
    (50.0, 0.6, (39.0, 13.0)),
    (50.0, 0.8, (32.5, 8.0)),
    (50.0, 1.0, (29.5, 5.0)),
])
def test_rao_angles_follow_sp125_figure_414(expansion_ratio, length_fraction, expected):
    # Independent readings of the scanned chart, at its stated precision.
    assert rao_angles(expansion_ratio, length_fraction) == pytest.approx(expected, abs=0.5)


def test_rao_angles_have_published_expansion_and_length_trends():
    ratios = [5.0 + index * 0.5 for index in range(91)]
    fractions = [0.6 + index * 0.01 for index in range(41)]
    for fraction in fractions:
        angles = [rao_angles(ratio, fraction) for ratio in ratios]
        assert all(right[0] >= left[0] - 1e-12 for left, right in zip(angles, angles[1:]))
        assert all(right[1] <= left[1] + 1e-12 for left, right in zip(angles, angles[1:]))
    for ratio in ratios:
        angles = [rao_angles(ratio, fraction) for fraction in fractions]
        assert all(0 < exit_angle < initial < 90 for initial, exit_angle in angles)
        assert all(right[0] <= left[0] + 1e-12 and right[1] <= left[1] + 1e-12
                   for left, right in zip(angles, angles[1:]))


@pytest.mark.parametrize("ratio,fraction", [
    (1.0, 0.8), (-2.0, 0.8), (14.0, 0.4999), (14.0, 1.2001),
    (float("nan"), 0.8), (float("inf"), 0.8), (14.0, float("nan")),
    (14.0, float("inf")),
])
def test_rao_angles_reject_invalid_values_without_clipping(ratio, fraction):
    with pytest.raises(ValueError, match="Rao automatic angles require"):
        rao_angles(ratio, fraction)

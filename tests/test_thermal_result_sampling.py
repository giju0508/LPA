from __future__ import annotations

from lpa.ui.result_views import ThermalResultsPage


def test_representative_indices_include_endpoints_without_duplicates() -> None:
    indices = ThermalResultsPage._representative_indices(700)
    assert len(indices) == 30
    assert indices[0] == 0
    assert indices[-1] == 699
    assert indices == sorted(set(indices))


def test_representative_indices_keep_short_results_complete() -> None:
    assert ThermalResultsPage._representative_indices(4) == [0, 1, 2, 3]
    assert ThermalResultsPage._representative_indices(0) == []

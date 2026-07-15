from __future__ import annotations

import json

import pytest

from lpa import __version__
from lpa.project import (
    DEFAULT_PROJECT_EXTENSION,
    LEGACY_PROJECT_EXTENSIONS,
    PROJECT_SCHEMA,
    load_project,
    make_project,
    save_project,
)


def _sample_project() -> dict[str, object]:
    return make_project(
        {
            "engine_name": "CFG round-trip 엔진",
            "description": "UTF-8 프로젝트 저장 검증",
        },
        {"contraction_area_ratio": "4"},
        {"thermal_enabled": False, "segments": []},
    )


def test_cfg_round_trip_preserves_schema_version_and_unicode(tmp_path) -> None:
    project = _sample_project()
    assert DEFAULT_PROJECT_EXTENSION == ".cfg"
    target = tmp_path / f"engine{DEFAULT_PROJECT_EXTENSION}"

    assert save_project(target, project) == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema"] == PROJECT_SCHEMA == "lpa-project/1"
    assert payload["application_version"] == __version__ == "0.7.0"
    assert payload["engine"]["engine_name"] == "CFG round-trip 엔진"
    assert load_project(target) == project


@pytest.mark.parametrize(
    "filename",
    [f"legacy{extension}" for extension in LEGACY_PROJECT_EXTENSIONS],
)
def test_load_project_keeps_legacy_json_extension_compatibility(tmp_path, filename: str) -> None:
    project = _sample_project()
    target = tmp_path / filename
    target.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

    assert load_project(target) == project

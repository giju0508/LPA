from __future__ import annotations

import ast
import re
from datetime import datetime
from pathlib import Path

from lpa import __version__
from lpa.app import APP_TITLE


ROOT = Path(__file__).resolve().parents[1]


def test_readme_current_version_matches_application():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"현재 버전: **{__version__}**" in readme


def test_latest_changelog_release_matches_version_and_has_kst_timestamp():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = next(line for line in changelog.splitlines() if line.startswith("## "))
    match = re.fullmatch(r"## (\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?) — (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) KST", heading)
    assert match is not None, heading
    assert match.group(1) == __version__
    datetime.strptime(match.group(2), "%Y-%m-%d %H:%M:%S")


def test_windows_fixed_and_string_versions_match_application():
    # Parse the PyInstaller resource as data without executing its constructors.
    tree = ast.parse((ROOT / "lpa_version_info.txt").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)]
    fixed = next(node for node in calls if node.func.id == "FixedFileInfo")
    values = {keyword.arg: ast.literal_eval(keyword.value) for keyword in fixed.keywords}
    version = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?", __version__)
    assert version is not None, __version__
    expected = tuple(int(version.group(index)) for index in (1, 2, 3)) + (int(version.group(5) or 0),)
    assert values["filevers"] == values["prodvers"] == expected
    assert values["mask"] & 0x2
    assert values["flags"] & 0x2 == (0x2 if version.group(4) else 0)
    strings = {ast.literal_eval(node.args[0]): ast.literal_eval(node.args[1])
               for node in calls if node.func.id == "StringStruct"}
    assert strings["FileVersion"] == strings["ProductVersion"] == __version__


def test_application_title_identifies_beta_release():
    assert __version__ in APP_TITLE
    if re.search(r"b\d+$", __version__):
        assert "Beta" in APP_TITLE

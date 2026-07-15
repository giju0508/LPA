from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from lpa.core.rocketcea_runtime import _is_fortran_safe_path


def test_pyinstaller_spec_collects_all_rocketcea_work_files() -> None:
    """Keep the initial Fortran output unit in the one-file distribution."""

    spec = (Path(__file__).resolve().parents[1] / "LPA.spec").read_text(encoding="utf-8")
    for name in ("f.inp", "f.out", "temp.dat", "thermo.lib", "trans.lib"):
        assert f'"{name}"' in spec


def test_legacy_cea_path_filter_catches_spaces_and_non_ascii() -> None:
    assert _is_fortran_safe_path(r"C:\Users\PlainUser")
    assert _is_fortran_safe_path("Z:\\")
    assert not _is_fortran_safe_path(r"C:\Users\First Last")
    assert not _is_fortran_safe_path(r"C:\Users\홍길동")


@pytest.mark.skipif(os.name != "nt", reason="RocketCEA Windows path compatibility")
@pytest.mark.parametrize("profile_name", ("User Profile With Spaces", "사용자 프로필"))
def test_rocketcea_uses_safe_alias_without_writing_c_drive(
    tmp_path: Path,
    profile_name: str,
) -> None:
    fake_home = tmp_path / profile_name
    fake_home.mkdir()
    script = r'''
from pathlib import Path
from lpa.core.models import EngineDefinition
from lpa.core.performance import RocketCEAAdapter

adapter = RocketCEAAdapter()
assert adapter.available, adapter.unavailable_reason
from rocketcea import cea_obj
cea = adapter._make_cea(EngineDefinition(), 4.0)
isp, _, _ = cea.get_IvacCstrTc(Pc=20.0, MR=2.5, eps=10.0)
assert float(isp) > 1.0
assert Path.home().resolve() == Path.home()
assert cea_obj.get_rocketcea_data_dir().lower() != r"c:\userdata"
print(cea_obj.get_rocketcea_data_dir())
'''
    environment = os.environ.copy()
    environment.update(
        {
            "USERPROFILE": str(fake_home),
            "HOME": str(fake_home),
            "HOMEDRIVE": fake_home.drive,
            "HOMEPATH": str(fake_home)[len(fake_home.drive) :],
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    work_dir = fake_home / "RocketCEA"
    assert {"f.inp", "f.out", "temp.dat", "thermo.lib", "trans.lib"} <= {
        path.name for path in work_dir.iterdir()
    }
    assert "C:\\UserData" not in completed.stdout

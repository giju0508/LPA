from __future__ import annotations

import builtins
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import main as launcher
from lpa import logging_config


@pytest.fixture
def isolated_launcher(monkeypatch):
    monkeypatch.setattr(launcher, "_configure_windows_app_identity", lambda: None)
    monkeypatch.setattr(launcher, "_configure_windows_dpi", lambda: None)
    monkeypatch.setattr(logging_config, "configure_logging", lambda: None)
    return launcher


def _replace_app_import(monkeypatch, replacement):
    original_import = builtins.__import__

    def import_app(name, *args, **kwargs):
        if name == "lpa.app":
            return replacement()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_app)


def test_launcher_interrupt_during_gui_import_returns_cancel_code(isolated_launcher, monkeypatch, caplog):
    def interrupt():
        raise KeyboardInterrupt

    _replace_app_import(monkeypatch, interrupt)
    with caplog.at_level(logging.INFO, logger="lpa"):
        assert isolated_launcher.main() == 130
    assert "Startup cancelled by an interrupt" in caplog.text
    assert sys.executable in caplog.text


def test_launcher_interrupt_during_gui_construction_returns_cancel_code(isolated_launcher, monkeypatch):
    def interrupt():
        raise KeyboardInterrupt

    _replace_app_import(monkeypatch, lambda: SimpleNamespace(run=interrupt))
    assert isolated_launcher.main() == 130


def test_launcher_success_runs_application_once(isolated_launcher, monkeypatch):
    calls = []
    _replace_app_import(monkeypatch, lambda: SimpleNamespace(run=lambda: calls.append("run")))
    assert isolated_launcher.main() == 0
    assert calls == ["run"]


def test_launcher_preserves_actual_import_failures(isolated_launcher, monkeypatch):
    def missing_module():
        raise ModuleNotFoundError("test dependency missing", name="test_dependency")

    _replace_app_import(monkeypatch, missing_module)
    with pytest.raises(ModuleNotFoundError, match="test dependency missing"):
        isolated_launcher.main()


def test_script_entry_import_interrupt_has_no_traceback(tmp_path):
    entry = Path(launcher.__file__).resolve()
    script = """
import builtins, runpy, sys
original_import = builtins.__import__
def interrupt_app(name, *args, **kwargs):
    if name == 'lpa.app':
        raise KeyboardInterrupt
    return original_import(name, *args, **kwargs)
builtins.__import__ = interrupt_app
runpy.run_path(sys.argv[1], run_name='__main__')
"""
    environment = dict(os.environ, LOCALAPPDATA=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(entry)],
        cwd=entry.parent, env=environment, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 130
    assert result.stdout == result.stderr == ""
    log = (tmp_path / "LPA" / "logs" / "lpa.log").read_text(encoding="utf-8")
    assert "Startup cancelled by an interrupt" in log

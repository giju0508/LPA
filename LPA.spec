# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file specification for LGJ Propulsion Analysis."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


ROOT = Path(SPECPATH).resolve()
RESOURCE_DIR = ROOT / "lpa" / "resources"


ROCKETCEA_RUNTIME_MODULES = {
    "rocketcea",
    "rocketcea.blends",
    "rocketcea.cea_obj",
    "rocketcea.cea_obj_w_units",
    "rocketcea.find_mingw_lib",
    "rocketcea.Goal",
    "rocketcea.input_cards",
    "rocketcea.Isp",
    "rocketcea.py_cea",
    "rocketcea.separated_Cf",
    "rocketcea.units",
}


def _required_rocketcea_module(name: str) -> bool:
    """Collect the runtime graph used by pinned RocketCEA 1.2.3."""

    return name in ROCKETCEA_RUNTIME_MODULES


# RocketCEA loads its Fortran extension and CEA databases at runtime.  The
# include list keeps only the files copied by rocketcea.cea_obj into its
# writable per-user work directory; the package collector also finds py_cea.
# f.out is an initialized Fortran output-unit template, not an optional result:
# omitting it makes the compiled solver terminate before its first calculation.
rocketcea_datas, rocketcea_binaries, rocketcea_hiddenimports = collect_all(
    "rocketcea",
    include_py_files=True,
    filter_submodules=_required_rocketcea_module,
    include_datas=[
        "_version.py",
        "f.inp",
        "f.out",
        "temp.dat",
        "thermo.lib",
        "trans.lib",
    ],
    on_error="raise",
)

datas = [
    (str(RESOURCE_DIR / "logo.ico"), "lpa/resources"),
    (str(RESOURCE_DIR / "rao_contour_reference.png"), "lpa/resources"),
]
datas += rocketcea_datas
coolprop_datas, coolprop_binaries, coolprop_hiddenimports = collect_all(
    "CoolProp", include_py_files=False,
    filter_submodules=lambda name: not any(part in name for part in (".Plots", ".tests")),
    on_error="raise",
)
datas += coolprop_datas
# scipy.optimize is used by the pseudocritical Cp-peak diagnostic. Preserve
# its bundled license notices along with the runtime collected by its hooks.
datas += copy_metadata("scipy")
datas += copy_metadata("ht")
datas += copy_metadata("fluids")
datas += copy_metadata("rocketcea")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=rocketcea_binaries + coolprop_binaries,
    datas=datas,
    hiddenimports=rocketcea_hiddenimports + coolprop_hiddenimports + [
        "rocketcea.cea_obj",
        "rocketcea.cea_obj_w_units",
        "rocketcea.py_cea",
        "matplotlib.backends.backend_tkagg",
    ],
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["TkAgg"]}},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "pytest",
        "rocketcea.biprop_utils",
        "rocketcea.examples",
        "rocketcea.tests",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LPA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(RESOURCE_DIR / "logo.ico"),
    version=str(ROOT / "lpa_version_info.txt"),
)

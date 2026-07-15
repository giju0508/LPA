[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = $PSScriptRoot
$VenvRoot = Join-Path $ProjectRoot ".venv-build"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$SpecFile = Join-Path $ProjectRoot "LPA.spec"
$OutputExe = Join-Path $ProjectRoot "dist\LPA.exe"

Set-Location -LiteralPath $ProjectRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher (py.exe) was not found. Install 64-bit CPython 3.14 from python.org."
}

& py -3.14 -c "import struct, sys; assert sys.version_info[:2] == (3, 14); assert struct.calcsize('P') == 8"
if ($LASTEXITCODE -ne 0) {
    throw "A 64-bit CPython 3.14 installation is required."
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host "Creating build environment: $VenvRoot"
    & py -3.14 -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the build environment." }
}

if (-not $SkipInstall) {
    Write-Host "Installing pinned runtime and build dependencies..."
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Failed to update pip." }
    & $VenvPython -m pip install --requirement requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Failed to install build dependencies." }
}

Write-Host "Checking GUI, numerical libraries, and RocketCEA resources..."
$Preflight = @'
import pathlib
import struct
import sys

assert sys.version_info[:2] == (3, 14), sys.version
assert struct.calcsize("P") == 8, "64-bit Python is required"

import tkinter
import matplotlib
import numpy
import scipy
import rocketcea
import rocketcea.py_cea
from rocketcea.cea_obj_w_units import CEA_Obj

root = pathlib.Path(rocketcea.__file__).resolve().parent
required_data = ("f.inp", "f.out", "temp.dat", "thermo.lib", "trans.lib")
missing = [name for name in required_data if not (root / name).is_file()]
assert not missing, f"Missing RocketCEA data: {missing}"
assert pathlib.Path(rocketcea.py_cea.__file__).suffix.lower() == ".pyd"

# A small call catches a mismatched Fortran extension before packaging.
cea = CEA_Obj(oxName="LOX", fuelName="RP-1", pressure_units="bar")
assert cea.get_Cstar(Pc=20.0, MR=2.5) > 0.0
print(f"Python {sys.version.split()[0]}, Tk {tkinter.TkVersion}")
print(f"NumPy {numpy.__version__}, SciPy {scipy.__version__}, Matplotlib {matplotlib.__version__}")
print(f"RocketCEA {rocketcea.__version__}: {root}")
'@
# Windows PowerShell can remove embedded quotes when a multiline string is
# forwarded to a native executable.  Base64 keeps the Python source intact
# across both Windows PowerShell 5.1 and PowerShell 7 argument handling.
$EncodedPreflight = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes($Preflight)
)
& $VenvPython -c "import base64; exec(base64.b64decode('$EncodedPreflight'))"
if ($LASTEXITCODE -ne 0) { throw "Dependency preflight failed." }

if (-not (Test-Path -LiteralPath $SpecFile -PathType Leaf)) {
    throw "LPA.spec was not found."
}

Write-Host "Building one-file Windows executable..."
& $VenvPython -m PyInstaller --noconfirm --clean $SpecFile
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
if (-not (Test-Path -LiteralPath $OutputExe -PathType Leaf)) {
    throw "Build finished without producing dist\LPA.exe."
}

Write-Host "Build complete: $OutputExe"
Write-Host "Run the validation checklist in docs\VALIDATION.md before distribution."

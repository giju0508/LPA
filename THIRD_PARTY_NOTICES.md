# Third-party components in LPA 0.18.0b1 Beta

The application uses the pinned packages in requirements.txt. Their original
copyright and license terms apply to those components. The Windows release ZIP
includes the installed distributions' license notices under third_party_licenses/.
The frozen executable also retains collected package metadata/license files.

| Component | Version | License / source |
|---|---|---|
| RocketCEA | 1.2.3 | GPL-3.0; https://pypi.org/project/rocketcea/1.2.3/ |
| CoolProp | 8.0.0 | MIT; https://github.com/CoolProp/CoolProp |
| ht | 1.2.0 | MIT; https://github.com/CalebBell/ht |
| fluids | 1.3.1 | MIT; https://github.com/CalebBell/fluids |
| NumPy | 2.4.2 | BSD and bundled third-party notices; https://numpy.org/ |
| SciPy | 1.17.0 | BSD and bundled third-party notices; https://scipy.org/ |
| Matplotlib | 3.10.8 | Matplotlib license and bundled font notices; https://matplotlib.org/ |

The release assets include the unmodified RocketCEA 1.2.3 source distribution,
with its SHA-256 checked against the version's PyPI metadata. Build instructions,
the LPA source at the matching Git tag, pinned requirements and PyInstaller spec
are provided alongside the binary. REFPROP is not bundled. RPA is used only for
comparison fixtures and is not a dependency or redistributed executable.

The 0.18 Beta adds LPA implementations of published mathematical correlations
and numerical property coefficients. Sources and calibration/holdout roles are
recorded in docs/property_review_0180.md, docs/TRAPP_TRANSPORT_2026-10-19.md,
docs/ETHANOL_TRANSPORT_2026-10-19.md and docs/MIXTURE_FLOW_BOILING_2026-10-19.md.
The public NIST TN1949 supplement supplies the trans-decalin EOS coefficients;
only the numerical model is represented in LPA code. No REFPROP DLL, licensed
REFPROP installation, commercial fluid database or original FLD file is bundled.
The new two-component RP-1 fit is LPA's engineering surrogate, not NIST's
published four-component model. Selected ThermoML numerical measurements retain
their original study DOI, units and provenance in the source test fixture;
the associated journal articles and publisher images are not redistributed.

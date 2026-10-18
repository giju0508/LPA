# 0.18.0b1 Beta 실행 기록

2026-10-19 KST, local Windows x64, CPython 3.14.0 / pinned runtime.
This directory preserves actual tool outputs. Numeric completion is not
physical validation. Private CFG input is identified by SHA-256 only and is
not copied here. Study data remain in tests/data with DOI provenance.

| File | Meaning |
|---|---|
| test_initial.txt | Initial integration: 1 failed / 789 passed; dense liquid was misrouted to Film gas restriction; fixed before final validation |
| test_run.txt | Full regression: 798 passed in 125.33 s |
| test_endpoint.txt | After final zero-liquid NaN enthalpy/Cp/density guard: 5 passed in 6.78 s |
| channel_run.txt / coolant_channel_validation.json | Full 300-station LNG/Et70 public cylinders and provided RP-1 1.3/1.8 mm cases; input unchanged; method/transport/phase evidence and warnings |
| build_run.txt | Final post-guard PyInstaller EXE build |
| archive_run.txt / archive_check.json | 39 LPA modules + main match final source; resources/native licenses; final EXE SHA-256 |
| source_smoke.json / exe_smoke.json | Real source and EXE GUI creation, responding, normal close and exit 0 |
| native_runtime_run.txt / isolated_runtime.json | Extracted EXE code/native under -I -S; source-independent property, CEA and boiling checks; host interpreter still used |
| pip_check.txt / compile_check.txt | No broken requirements and successful compilation |
| release_manifest.json | ZIP/member byte verification and EXE/ZIP/dependency-source SHA-256 and sizes |
| github_publication.json | Actual published prerelease response, tag/code commit and uploaded asset digests |
| anonymous_publication_check.json | Unauthenticated public repo/release and download checks after publication |

The screenshots and the six size/scaling cases are documented in
[UI layout review](../UI_LAYOUT_REVIEW_0180.md). Source stdout/stderr were empty.
Raw logs are retained byte-for-byte, including any trailing whitespace.
The final endpoint change was followed by rebuilding, bundle comparison and
native/GUI smoke again. No clean-PC/VM full-engine experiment, actual OS DPI
switch, signing, CHF/dryout/coking or channel hardware validation is asserted.

# 0.17.0b1 Beta verification evidence

- `property_and_channel_review.json`: 21 PT samples, eight mass-quality saturation states, property-specific evidence and the unchanged local RP-1 review case summary. No user project is copied into this repository.
- `publication_preflight.json`: credential-signature scan of the existing Git history; scope and limitations recorded without printing credential contents.
- `test_run.txt`, `build_run.txt`: final full regression and Windows build output.
- `archive_check.json`: executable Python code and resources compared with source, licenses and native bundle extraction checked.
- `native_runtime_check.json`: isolated extracted modules/native libraries, actual RocketCEA and water boiling energy balance. Uses the host CPython interpreter under `-I -S`; it is not a clean-PC frozen-GUI calculation certification.
- `source_smoke.json`, `exe_smoke.json`: actual source/EXE window startup and normal close on this Windows host.
- `release_manifest.json`: versioned binary/ZIP/source sizes, SHA-256 and byte-verified ZIP members.
- `github_publication.json`: public repository and published Beta prerelease, release code commit and matching server asset digests.

Read `../THERMAL_REVIEW_0170.md` and `../property_review_0170.md` before interpreting these software checks as physical validation. The RP-1 case stops at the supported default viscosity-temperature boundary; the last state is not a full-circuit outlet.

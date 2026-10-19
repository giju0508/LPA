# 0.18.1b1 Beta 검토·배포 근거

2026-10-19 KST. 원본 CFG는 수정하거나 저장소/배포 ZIP에 포함하지 않았다.
입력 SHA-256은 `b55b923eec14eaaa5778d31d1f6ddbd829221fd6fd2fc9ff53a64ec18c8ada33`.

| 파일 | 의미 |
|---|---|
| `nozzle_entry_baseline_0180.json` | 동일한 현재 CFG의 이전 코드 계산. 공개 기록의 회로 식별자는 익명화 |
| `nozzle_entry_validation.json` | 최종 코드 120/300/700셀 계산, 원본 미변경 확인, 에너지 수지·입구 진단·재료 판정 |
| `rp1_medium_temperature.png` | 실제 300셀 원시 온도 곡선, 냉각제 입구와 CuCrZr 참고 용융점. 적용성 invalid |
| `test_run.txt` | 최종 전체 회귀 원본 출력: 867 passed / 176.43 s |
| `build_run.txt` | 최종 PyInstaller 빌드 원본 출력 |
| `targeted_final.txt` | 최종 국소 벽/재료 판정 관련 42개 회귀 출력 |
| `case_validation_run.txt` | 최종 실제 입력 3격자 재현 도구 출력 |
| `pip_check.txt`, `compileall.txt` | 의존성 일관성·Python 문법 검사 출력 |
| `archive_check.json`, `archive_check_run.txt` | EXE 내부 최종 소스 39모듈+main·리소스/라이선스 일치 |
| `isolated_runtime.json`, `native_runtime_run.txt` | 추출 코드/native의 isolated 실행. host interpreter 사용이며 clean-PC 검증과 구분 |
| `source_smoke.json`, `source_smoke_run.txt` | 실제 소스 GUI 응답·정상 닫기·exit 0 |
| `source_stdout.txt`, `source_stderr.txt` | 소스 GUI 출력, 각각 0 bytes |
| `exe_smoke.json`, `exe_smoke_run.txt` | 실제 frozen EXE GUI 응답·정상 닫기·exit 0 |
| `release_manifest.json`, `package_run.txt` | 최종 EXE/ZIP/대응 RocketCEA 소스의 크기·SHA-256 및 ZIP member 검증 |
| `github_publication.json`, `publish_run.txt` | 실제 공개 GitHub prerelease·commit·각 uploaded asset의 서버 digest |
| `anonymous_publication_check.json`, `public_check_run.txt`, `PUBLICATION.md` | 인증 없는 공개 repo/release/tag·다운로드 확인 및 게시 기록 |

`.txt`는 실제 도구 출력 파일을 byte 단위로 복사한다. PowerShell 리다이렉트의
인코딩과 줄바꿈을 보존하며 Git text normalization도 적용하지 않는다.
게시 전 검증 문서는 release ZIP에 포함한다. 게시 완료 기록은 immutable
release code tag를 바꾸지 않고 후속 기록 commit으로 저장한다.

방법과 한계는 [열검토](../THERMAL_REVIEW_0181.md),
[UI 검수](../THERMAL_INLET_RESULT_UI_0181.md),
[버전별 검증](../VALIDATION.md)을 참조한다. 수치 수렴과 에너지 수지는
용융 참고값을 초과한 고체벽 결과의 물리적 유효성을 보장하지 않는다.

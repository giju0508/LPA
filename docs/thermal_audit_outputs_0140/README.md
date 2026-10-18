# LPA 0.14.0 열전달 검증 산출물

2026-10-11, CPython 3.14.0 / RocketCEA 1.2.3 / CoolProp 8.0.0. 실측 연소시험이 아닌 계산식·EOS·수지·적용범위 검증 자료다.

- `audit/station_audit.csv`: 실제 GOX/GCH4 CEA 입력의 300 station, 생산 Bartz와 독립 factor별 계산 대조.
- `audit/summary.json`: 실제 입력, 단상 구간 열수지, 전체 물리 진단 및 출처.
- `audit/axial_convergence.csv`: 350/700/1400 station × gray-gas epsilon 0/.02/.08/.16. 이 조건은 2상 영역 때문에 모두 **unsupported**이며 남는 값은 유효 단상 부분/비등을 제외한 후보값이다.
- `audit/bartz_sensitivity.csv`: 지정 물성·곡률 perturbation의 식 민감도.
- `coolant_case_matrix.csv`, `pressure_state_matrix.csv`, `thermal_method_benchmarks.json`: 8 coolant, 9 기체 압력 상태, 3 radiation parameter 시나리오. 원통 기준 gas는 명시된 상수 gamma 및 screening transport를 사용한다. `water:` 진단 접두어는 기준 segment ID이며 모든 coolant가 물이라는 뜻이 아니다.

재생성 명령:

```powershell
.\.venv-build\Scripts\python.exe -B -m tools.thermal_audit --station-count 300 --output-dir docs/thermal_audit_outputs_0140/audit
.\.venv-build\Scripts\python.exe -B -m tools.thermal_release_benchmarks --output-dir docs/thermal_audit_outputs_0140
.\.venv-build\Scripts\python.exe -B -m tools.regen_feed_benchmark --output docs/thermal_audit_outputs_0140/partial_feed_feedback.json
```

phase 제한으로 일부 온도가 NaN인 경우, 남은 최대 온도와 격자 수렴만으로 전 구간의 정확성/설계 적합성을 판단할 수 없다. 원본 JSON/CSV와 [항목별 신뢰도 평가](../RELEASE_REMEDIATION_2026-10-11.md)를 함께 확인한다. runtime의 프로세스별 CEA 작업 폴더와 앱 내 직렬화로 동시 계산의 공유 파일/배열 충돌을 방지한다.

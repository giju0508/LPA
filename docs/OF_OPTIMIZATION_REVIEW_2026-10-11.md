# RPA 자동 O/F 및 LPA maximum C* 기준 검토

검토일: 2026-10-11 KST. 최초 대상: LPA 0.14.0과 설치된 RPA 4.0.13 번들의 공식 scripting API. 아래 최초 검토는 0.14.0의 C* 목적함수에 대한 기록이다. 후속 지시에 따라 **0.15.0에서 Maximum theoretical vacuum Isp로 변경 완료**했으며, 변경 내용·검증·신뢰도는 문서 끝의 후속 적용 기록에 정리했다.

## 판정

RPA 공식 문서는 자동 O/F의 목적을 **최대 비추력**으로 설명한다. 실제 설치본의 고정 확장비 검증에서는 **이론 진공 Isp 최대점**과 일치했다. 현재 LPA의 **maximum C***는 별도의 연소기 평가 목적함수로 타당하지만, RPA 자동 O/F와 같거나 엔진 전체 비추력을 최대화한다고 설명할 수 없다.

LPA의 기본 엔진 자동 최적화 목표로는 RPA와 맞추는 `Maximum theoretical vacuum Isp`를 권고한다. 운전 성능을 최적화하려면 설계 외압에서의 delivered Isp와 물리 적용범위 제약을 별도 선택으로 제공해야 한다. C* 최대화는 명시적인 별도 옵션으로 유지할 수 있다.

## 공식 자료와 실제 RPA 대조

- [RPA v4 User Manual](https://rocket-propulsion.com/downloads/4/docs/RPA_4_User_Manual.pdf), 인쇄 p12: optimum mixture ratio를 maximum specific impulse로 정의한다. p90의 `PropellantConfiguration.optimize`도 같은 목적을 명시한다. 이 문장만으로 vacuum/ambient 또는 theoretical/delivered의 세부 선택을 확정하지 않았다.
- [RPA 공식 기능 목록](https://rocket-propulsion.com/RPA/features.htm)도 최대 비추력 최적화를 명시한다.
- 실제 설치본: `RPA.exe` FileVersion 4.0.13.0, `RPA-Script.exe` 4.0.8.0, `performance4.dll` 4.0.0.0. 공식 `ConfigFile`의 `mixtureRatio.type="OPTIMUM"`→`PropulsionAnalysis`와 `TheoreticalPerformance`의 `optimize=true`를 각각 사용했고 결과가 일치했다. GUI와 같은 configuration 경로를 사용했고 throat 20 mm·80% parabolic sizing을 유지한 두 사례도 같은 자동 O/F임을 확인했다. GUI 버튼을 직접 조작한 시험은 아니다.

LOX/RP-1, Pc=20 bar, Ac/At=6.25, shifting equilibrium, 기본 반응물 상태에서 같은 RPA backend의 61점 탐색 및 golden-section 30회 정련으로 대조했다.

| Ae/At | RPA 자동 O/F | 독립 최대 C* O/F | 독립 최대 이론 진공 Isp O/F | 독립 최대 delivered 진공 Isp O/F |
|---:|---:|---:|---:|---:|
| 5 | 2.3714936 | 2.1969939 | 2.3715429 | 2.3715429 |
| 40 | 2.6764996 | 2.1969939 | 2.6765955 | 2.6528848 |

RPA 자동값과 이론 진공 Isp 최대점은 O/F 0.0001 이내에서 일치한다. 특히 확장비 40에서 delivered 최대점과 차이가 있어 **이론 진공 Isp 목적**이라는 판별 근거가 된다. 같은 C* 최대점에서는 진공 Isp가 각각 약 0.999 s / 7.397 s 낮았다. 이 비교는 서로 다른 프로그램의 데이터베이스 오차를 최적화 목적함수 차이로 오인하지 않도록 RPA 내부에서 수행했다.

추가로 확장비 40의 throat-frozen에서는 자동 O/F=2.3108499, 출구압 1 atm 지정에서는 2.4352325였다. LOX/Ethanol 70 wt%의 확장비 5/40 자동값은 1.3142976/1.4223213이었다. 노즐 조건과 화학 유동 모델이 자동 최적점에 영향을 준다.

범위 제한: 고정 확장비 5/40에서 목적함수를 정량 대조했다. 다른 모든 버전·추진제·Film·nozzle-off 경로의 내부 목적함수를 인증한 것은 아니다. 첫 광범위 TP 실행은 LH2 사례 처리 중 native exit 1로 종료되어 완료된 6사례만 사용했다. 별도의 GUI configuration 2사례 및 독립 RP-1 탐색은 exit 0이었다. 확장비 40의 무박리 해면 Isp는 음수여서 외압 최적화 근거로 사용하지 않았다. 사용한 독립 탐색법을 RPA의 내부 구현이라고 주장하지 않는다.

## LPA 0.14.0 구현과 수치 영향

`lpa/core/performance.py`의 `RocketCEAAdapter.cstar_evaluator`는 `get_Cstar(Pc, MR)`를 직접 최대화한다. 노즐 출구 및 frozen 조건은 선택된 O/F의 Isp/출구 상태를 평가하는 데 사용한다. 반환 `vacuum_isp_s`는 C* 최대점에서의 값이며 Isp의 최대값은 아니다.

고정 Ac/At에서는 이 목적함수가 확장비와 downstream freezing에 독립이다. 고정 Dc와 명목 추력의 결합에서는 노즐 조건→목 면적→Ac/At의 반복 연결로 간접 영향이 생길 수 있다.

별도의 실제 RocketCEA 1.2.3 + LPA 반응물 카드로, 101점 탐색 후 모든 국소 최대 후보를 bounded 정련했다. 아래는 **이론 진공 Isp** 비교이며 LPA의 98% 경험 효율이나 Film을 반영한 실측 delivered 성능이 아니다.

| 추진제 | Pc / Ac/At / Ae/At | LPA C* 최적 O/F | 진공 Isp 최적 O/F | C* 최적점을 사용한 Isp 손실 |
|---|---|---:|---:|---:|
| LOX / Ethanol 70 wt% | 20 bar / 6.25 / 5 | 1.2348 | 1.3134 | 0.815 s, 0.292% |
| LOX / Ethanol 70 wt% | 20 bar / 6.25 / 40 | 1.2348 | 1.4222 | 5.490 s, 1.676% |
| LOX / LH2 | 100 bar / 6.25 / 40 | 3.3385 | 4.7587 | 5.910 s, 1.298% |

LOX/Et70, 확장비 5의 부착 해면 성능 최대점은 O/F=1.32188이다. 진공 최적점과 외압 최적점도 구분해야 한다. RPA와 RocketCEA의 절대값 차이는 데이터베이스·반응물 카드·압력 기준 차이가 포함되어 있으므로 이 표와 RPA 표의 수치가 정확히 같아야 하는 것은 아니다.

같은 압력 기준으로 정의하면 `Isp=Cf*C*/g0`이다. C* 최대점에서 dC*/d(O/F)=0이어도 Cf가 변하면 dIsp/d(O/F)는 0이 아니다. 따라서 C*는 노즐을 포함한 추진제 소비 대비 추력 최대화의 충분한 기준이 아니다. [NASA의 Isp/추력 정의](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/specific-impulse/).

추가 정합성: LPA 탐색은 CEA의 raw Pinf-reference C*, 성능/유량 계산은 Pinj-reference C*를 사용한다. Et70, Ac/At=6.25의 두 C* 최대 O/F는 약 1.234799/1.234364로 소폭 다르다. 따라서 현재 탐색이 결과표의 보정 C*까지 정확히 최대화한다고 설명해서도 안 된다. [RocketCEA FAC 입력 압력 기준](https://rocketcea.readthedocs.io/en/stable/finite_area_comb.html).

## 적용 권고와 신뢰도

| 설계 목적 | 권고 목표 |
|---|---|
| RPA 자동 O/F의 관측 동작과 맞추기 | 동일 반응물 상태·Pc·Ac/At·출구조건·frozen 모델의 maximum theoretical vacuum Isp |
| 특정 운전 외압의 추진제 소비 최소화 | 해당 외압에서 maximum delivered Isp. 박리/비초크/미지원 조건 제외 및 열·유량 제약 병행 |
| 노즐과 분리한 연소기 비교 | maximum C*, 사용 압력 기준과 이론/보정 정의를 명시 |
| 실제 엔진/발사체 전체 최적화 | Isp와 함께 냉각성·벽온도·연소 안정성·coking·유량비·탱크 부피/질량·feed system 및 임무 조건을 제약/목적에 포함 |

실제 엔진의 운전 O/F는 최대 Isp와 달라질 수 있다. NASA의 [고/가변 O2/H2 혼합비 연구](https://ntrs.nasa.gov/citations/19900019322)는 밀도와 임무 성능 때문에 낮은 고도의 Isp 일부를 희생하는 사례를 제시한다. C* 최대화만으로 냉각성이나 구조 안전성을 보장하지 않는다.

공식 문헌의 최대 Isp 정의와, 이번 고정 확장비에서 RPA의 이론 진공 Isp 목적 판별 신뢰도는 **높음**이다. 실제 엔진/임무의 최적 O/F 또는 모든 RPA 내부 분기까지 확정한 것은 아니다. 최초 검토에서 확인한 README의 목적함수 설명 불일치는 후속 0.15.0에서 수정했다.

재현 자료: `docs/of_objective_review_20261011/rpa_objective_summary.json`(개인 라이선스 출력 제외), `rpa_gui_optimum.js`, `rpa_scan.js`, `cea_comparison_results.json`, `cea_objective_optima.csv`, `cea_isp_penalties.csv`, `cea_grid_points.csv`, `reproduce_objective_comparison.py`.

## 후속 적용 및 자체 평가 — LPA 0.15.0

사용자 지시에 따라 자동 최적화의 목적을 **Maximum theoretical vacuum Isp**로 변경했다. 목적함수와 출구조건 의미를 RPA의 검증된 동작에 맞췄으며, RocketCEA/RPA 데이터베이스와 비공개 탐색 설정의 완전한 수치 일치를 주장하지 않는다.

| 항목 | 적용 및 검증 결과 | 자체 평가 |
|---|---|---|
| 목적함수 | 후보마다 CEA `get_IvacCstrTc` 또는 `getFrozen_IvacCstrTc`의 이론 진공 Isp를 평가. raw C* API는 호환 유지하며 반환 C*는 선택점의 참고값 | 높음: 실제 CEA 독립 탐색, 저장된 10조건 기준값 및 O/F 주변값 대조 |
| 출구조건·동결 | 고정 Ae/At 유지, 고정 Pe에서 후보별 Ae/At 재계산. shifting/throat-frozen flags 일치. FAC chamber-frozen은 명시적으로 거부 | 높음: native 직접 Pe 지정과 별도 면적비 경유 대조. CEA 고정 Pe 반복잔차는 상대 약 3.2×10⁻⁵, Isp 약 0.00062 s이며 허용치에 기록 |
| 손실 제외 | 고정 Ac/At에서 반응효율·노즐효율·Film·설계 외압을 바꿔도 자동 O/F 유지 | 높음: 이론 목적과 delivered 성능을 구분하는 회귀 통과 |
| 직접 Dc 결합 | 직접 Dc+명목추력에서 선택 O/F와 유효 Ac/At 반복, 미수렴 경고 | 높음: 기존 사이징 결합 회귀 유지. 간접 형상 의존은 정상 |
| 조성·공급 상태 | 농도·온도·압력을 CEA 반응물 카드와 최적화 cache에 반영 | 높음: 실제 카드 및 독립 EOS 엔탈피를 사용하는 사례 대조 |
| backend·냉각 유량 | 분석 시 재최적화, 선택 MR로 core/thermal 입력 모두 재구성. 자동 모드의 비활성 수동 MR 무효값 무시, 원본 입력 보존 | 높음: 실 CEA 성능, 외부 Film 질량 ledger 및 엔진 냉각 유량 대조 |
| 공급 피드백 | 각 반복의 공급 T/P로 자동 O/F 재선택. 실제 CEA+CoolProp 부분 5 mm Regen 사례는 8회 수렴; O/F 1.3369407→1.3349807, 최종 공급 T 313.9230 K/P 249.2482 bar | 연결 구현 신뢰도 높음. 열 정확도는 기존 screening 유지; 전체 엔진 벽온도·하드웨어 검증이 아님 |
| 오류·fallback | 무효 Isp 후보 제외 및 경고, 전부 실패하면 미검증 ideal-gas vacuum-Isp screening으로 표시. frozen/공급 엔탈피 미반영을 명시, bound/zero Pe cap 진단 | 오류 전파 신뢰도 높음. fallback 물리 정확도는 낮음이며 CEA/RPA 최적값으로 취급하지 않음 |
| UI·프로젝트 | 새 목적 문구, 관련 입력 trace/cache 갱신, 결과 진단 메타데이터. 1080×700/Tk scaling 1.333/1.667/2.0에서 checkbox clipping 해결. 공급압 공란 안내도 실제 기준과 일치 | 높음: UI/프로젝트 회귀 유지. 실제 OS DPI 전환 시험과는 구분 |

대표 실제 CEA 결과: LOX/Et70, Pc 20 bar, Ac/At 6.25, 기준 반응물 상태.

| 유동/확장비 | 새 자동 O/F | 최대 이론 진공 Isp |
|---|---:|---:|
| shifting / 5 | 1.31342082 | 278.71864135 s |
| shifting / 40 | 1.42220763 | 327.53234783 s |
| throat-frozen / 40 | 1.24797405 | 312.13814649 s |

전체 `pytest tests`: **564 passed in 65.78s**, 실패·skip 없음. 독립 목적함수 검증은 `tests/test_vacuum_optimization_oracles.py`, backend/피드백 검증은 `tests/test_vacuum_optimization_service.py`에 있다. 실제 부분 Regen 재현 결과는 [auto_feed_feedback_0150.json](of_objective_review_20261011/auto_feed_feedback_0150.json)이며 다음 명령으로 재생성한다.

```powershell
.\.venv-build\Scripts\python.exe tools/regen_feed_benchmark.py --automatic-of --output docs/of_objective_review_20261011/auto_feed_feedback_0150.json
```

배포 검증 및 EXE/ZIP SHA-256은 [VALIDATION.md](VALIDATION.md)의 0.15.0 기록을 참조한다.

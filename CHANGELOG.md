# LPA 변경 이력

모든 시각은 대한민국 표준시(KST, UTC+09:00) 기준입니다.

## 0.16.0b2 — 2026-10-19 03:54:45 KST

1. GUI mainloop에 들어가기 전 Matplotlib/Tk 등 시작 import 도중에도 `KeyboardInterrupt`를 명시적인 실행 중단으로 처리하도록 launcher의 포착 범위를 넓힙니다. 중단을 기록하고 종료 코드 130을 반환하며, 실제 import/라이브러리 오류는 그대로 노출합니다.
2. VS Code Python 확장의 인터프리터 선택과 Code Runner의 별도 executor/PATH 설정을 구분하는 실행 안내를 추가합니다. 의존성은 실행에 쓰는 동일한 Python의 `-m pip install --requirement requirements.txt`로 설치하도록 안내하며, traceback의 마지막 import 위치만으로 Matplotlib 결함을 단정하지 않습니다.
3. Python·README·Windows 문자열 버전을 `0.16.0b2`, 고정 버전을 `0.16.0.2`로 맞추고 Beta/prerelease 표기를 유지합니다. 0.16.0b1의 열전달 기능·검증 기록은 이전 Beta 이력으로 보존하며, b2의 실제 시험·빌드·해시는 `docs/VALIDATION.md`에 별도로 기록합니다.

## 0.16.0b1 — 2026-10-19 01:59:25 KST

1. 재생냉각의 순수유체 포화 2상 구간을 계산하는 **Beta** 경로를 추가합니다. `auto`는 수력직경 0.19–3.1 mm에 Li–Wu, 3.1 mm 초과–32 mm에 Chen–Bennett를 선택하며, Chen–Bennett 직접 선택은 3 mm 이상에서 허용합니다. 사각채널의 수력직경 적용과 유체별 상관식 신뢰도는 screening이며, 혼합물 2상 열전달·미지원 transport·근임계 상태는 진단 후 중단합니다.
2. 2상 마찰 압력손실에 Lockhart–Martinelli를, 가속 압력손실에 homogeneous equilibrium model을 사용합니다. 최대 증기 질량분율 0.7은 계산 보호 경계이며 실제 CHF/dryout 예측이 아닙니다. 범위를 벗어난 구간을 정상 계산값으로 채우지 않고 물리 상태·중단 이유를 보고합니다.
3. 기본 CoolProp HEOS의 압력/엔탈피 기반 상 판정과 물성 경로를 보강하고 선택적 REFPROP backend를 제공합니다. REFPROP 및 유체 데이터는 별도 설치·사용권이 필요하며 배포본에 포함하지 않습니다. `ht==1.2.0`, `fluids==1.3.1`을 런타임 의존성에 추가합니다.
4. 온도 그래프에 2상 영역의 음영·범례를 추가하고, 증기 질량분율·유동/비등 상태·모델 출처를 축방향 표, 전체 station CSV와 진단에 기록합니다. 수치 수렴과 계산 완료 station 수를 분리하며, 미계산 station의 온도는 공란/NaN으로 보존합니다.
5. Python·Windows 고정/문자열 버전과 창 제목을 `0.16.0b1 Beta`에 맞추고 Windows prerelease flag를 설정합니다. README를 실제 Beta 기능·지원 범위·설치 및 배포 절차에 맞춰 정리합니다. 최종 통합시험·빌드·해시는 실제 수행 결과를 `docs/VALIDATION.md`에 기록합니다.
6. 0.15.0까지의 자동 이론 진공 Isp O/F, Rao 자동/직접 각도, CEA 공급 상태와 성능 계산, 기존 Regen/Film/Radiation·프로젝트 호환 기능을 유지합니다. 이 변경 기록은 상관식 구현 및 표시 범위의 설명이며 전체 엔진의 물리 정확도나 실제 하드웨어 검증 완료를 의미하지 않습니다.

## 0.15.0 — 2026-10-11 22:05:00 KST

1. 자동 O/F를 **Maximum theoretical vacuum Isp**로 변경합니다. 현재 조성·공급 엔탈피·Pc·Ac/At·노즐 출구조건 및 shifting/throat-frozen 모델에서 이론 진공 비추력을 최대화하며, 반응효율·노즐 손실·Film·운전 외압은 목적함수에서 제외합니다.
2. 출구압 지정은 후보 O/F마다 확장비를 계산하고, 직접 Dc+명목추력은 선택 O/F와 유효 Ac/At를 반복 수렴합니다. 기존 raw C* evaluator API는 유지하며 C*는 선택점의 참고 메타데이터로 기록합니다.
3. 분석 실행 및 Regen 공급 피드백 반복에서도 자동 O/F를 다시 계산하여 성능·추진제 유량·냉각제 정규화에 같은 값을 적용합니다. 원본 입력을 보존하고 결과에 목적함수·적용 O/F·이론 Isp·출처·경고를 기록합니다.
4. UI 문구·Help·About와 입력별 재계산/cache 조건을 수정하고, 최소 창/확대 글꼴의 자동 O/F 문구 잘림 및 공급압 공란 안내를 교정합니다. 기존 프로젝트 schema와 수동 O/F를 유지합니다.
5. 실제 RocketCEA 독립 탐색, 확장비/동결/출구압/공급 상태, 손실 독립성, 실패/fallback 및 백엔드·냉각 피드백 회귀를 검증합니다. RPA 목적함수와 맞추며 데이터베이스·비공개 수치 설정까지 동일한 값임을 의미하지 않습니다.

## 0.14.0 — 2026-10-11 18:10:51 KST

1. 배포 전 검토의 P1/P2/P3를 수정하고 항목별 변경, 독립 시험, 구현 신뢰도 및 물리 검증 한계를 `docs/RELEASE_REMEDIATION_2026-10-11.md`에 기록합니다.
2. 박리/비초크 유동의 임의 Cf 바닥값을 제거하고 유효성·사이징 제약을 적용합니다. 동결 API flags, 유한면적 CEA 압력/C* 기준, divergence 손실, Film 운동량/압력추력, 반응효율 closure를 일치시킵니다. CEA 국소 열역학·transport와 형상 실제 곡률을 보고합니다.
3. CoolProp 8.0.0을 런타임과 단일 EXE에 포함합니다. 냉각제 EOS·상 판정·엔탈피 행진, fin·원통벽·사각채널 보정, 세그먼트 적분 보존, 연결 Film/Regen 반복 및 물리 유효성 상태를 추가합니다.
4. 공급 온도·압력과 LNG 공통 혼합물 엔탈피, Film 오리피스 출구 압력/국소 가스압, 기체 초크 및 flashing 제한, 엔진 냉각 회로 유량을 반영합니다.
5. 세그먼트 저장 변경 추적, 오래된 분석 결과 차단, 원자적 저장/프로젝트 로딩, 엄격한 수치 검증, 중복 이름 연결 ID, 전체 경고, 물리 상태, BLC 표시 기준, 원본 Thermal CSV 및 배율별 레이아웃을 개선합니다.
6. 전체 회귀·독립 물성/수지/형상 검증·패키징 결과와 잔여 검증 범위를 검증 기록에 보존합니다.

## 0.13.0 — 2026-10-08 09:16:06 KST

1. Rao 자동 각도의 확장비 5–50 제한을 제거했습니다. NASA 도표 안에서는 기존 보간을 유지하고, 밖에서는 공식 RPA 4.0.13 번들 스크립트 출력과 대조한 유동 기반 Tn/Te 관계식을 사용합니다. 단일 EXE 구성과 선택적 직접 각도 입력을 유지합니다.
2. RocketCEA의 실제 출구 Mach 수와 목·출구 등엔트로피 지수를 자동 작도에 전달합니다. 평형/동결 조건의 API 인자를 반영하며, 속성이 없는 CEA 어댑터와 이상기체 경로의 대체 값은 metadata에 구분합니다.
3. 자동 각도가 지정한 길이·목 원호와 양립하지 않으면 접선교점 구성 전에 각도를 유효 구간으로 조정하고 선호값·적용값과 경고를 기록합니다. 길이·원호 반경·출구 면적비는 유지하며, 해당 치수로 원호–포물선 형상 자체가 불가능한 경우 명확한 기하 오류를 표시합니다.
4. 실제 RPA 자동 출력 20개와 원본 입력·유동 상태·실행 파일 출처를 회귀 fixture로 보존했습니다. 확장비 2/4/100/250/1000, 길이비 50/80/120%, 동결 유동, 자동 입력 저장, 접선과 점 수에 대한 검증을 추가했습니다.
5. 버전·KST 변경 기록·Windows 리소스와 빌드/시험/검증 로그를 0.13.0으로 반영합니다. NASA/RPA 선택 경계의 각도 전환 및 RPA와 LPA의 열역학·기하 처리 차이를 근거 문서에 명시합니다.

## 0.12.0 — 2026-10-08 08:33:49 KST

1. Rao bell의 자체 경험 각도식을 NASA SP-125 Fig. 4-14의 확장비·길이비 보간으로 교체했습니다. 원문 예제 `Ae/At=14`, `80%`의 Tn 27.4°, Te 9.8°를 재현하며, 도표 판독 근사와 자동 입력 범위를 명시했습니다.
2. Tn/Te 직접 입력을 추가하고 두 칸을 비우면 자동 보간하도록 했습니다. 직접 각도를 포함한 CFG 저장·복원과 이전 프로젝트의 자동 모드 호환을 지원합니다.
3. 포물선 접선교점의 강제 제한을 제거하여 양끝 접선각을 보존하고, 원호·길이·각도가 양립하지 않는 형상은 입력 오류로 표시합니다. 원호와 포물선에 고정된 점 예산을 배분하여 정확한 출구와 요청한 점 수를 유지합니다.
4. 문헌 각도·확장비 및 길이비 추세·양끝 접선·출구 면적비·해상도별 점 수·기존 오류 재현·직접 입력에 대한 회귀 검증을 추가했습니다.
5. 프로그램·프로젝트 저장·Windows 실행 파일 버전과 README를 0.12.0으로 일치시키고, 기존 입력 화면의 정적 안내 제거 규칙에 맞춰 Rao 입력 안내문을 제거했습니다. 입력 오류 메시지와 계산 근거 문서는 유지합니다.
6. 버전 일치 검증과 빌드·검증 로그를 추가하여 Python 버전, 변경 이력, 화면 제목과 Windows 버전 리소스의 불일치를 확인합니다.

## 0.11.0 — 2026-09-18 15:44:32 KST

1. Engine Definition의 H2O2와 Ethanol 농도별 선택지를 단일 추진제 선택과 별도 질량 백분율 입력으로 통합하고, IPA에도 같은 물 희석 입력을 추가했습니다. 0보다 크고 100% 이하인 소수점 농도를 지원하며 나머지는 액체 물입니다.
2. 농도를 core 입력·CFG·CEA 조성별 카드·자동 O/F 캐시에 반영하고, 이전 농도별 프로젝트의 질량분율과 Engine oxidizer/fuel → Regen → Film 연결 조성을 보존합니다.
3. LNG를 추가하고 Wärtsilä의 상용 대표 조성(CH4/C2H6/C3H8/C4H10/N2 = 94/4.7/0.8/0.2/0.3 mol%)을 분자량으로 질량 환산해 적용했습니다. 액체 성분별 기준 엔탈피 혼합 모델이며 적용 조성을 화면에 표시합니다.
4. 전체 산화제·연료의 CEA 입력 상태와 물성 경로를 검토했습니다. N2O는 액체 기준 카드로, Propane 상태 표기는 액체로 일치시키고, IPA는 기본 카드의 기체 엔탈피 대신 NIST 액체 생성엔탈피를 사용합니다. 검토 근거와 냉각제 물성의 근사 범위는 `docs/PROPELLANT_AUDIT.md`에 기록했습니다.
5. 자동 O/F의 목적함수를 진공 Isp에서 연소실 이상 특성속도 C* 최대로 변경했습니다. fallback도 C*를 기준으로 하며 H2O2/N2O의 산소 유효 질량 및 수용액 희석에 따른 O/F 방향을 수정했습니다.
6. 기본 LPA Demonstrator를 2000 N @ 1 atm, Pc 20 bar(a), Ac/At 6.25, L* 1.2 m, O/F 1.3, LOX / Ethanol 70 wt%로 변경했습니다.
7. 질량분율·이전 프로젝트 호환·냉각제 연결·대표 LNG 조성·C*와 Isp 최대점 구분·실제 RocketCEA 전체 추진제 조합·최소 창 크기·기본 엔진에 대한 회귀 검증을 추가했습니다.
8. 프로그램 시작 시 기본 설명문의 초기 삽입이 사용자 편집으로 처리되어 저장 확인창이 뜨던 문제를 수정했습니다.

## 0.10.0 — 2026-07-21 19:42:36 KST

1. Regen의 Relative mass flow rate에 적용되던 100% 상한을 제거하고, 유효성 조건을 0보다 큰 값으로 변경했습니다.
2. 독립적인 `Custom coolant` Regen 회로의 질량유량을 `엔진 총유량 × 상대유량(%) / 100`으로 계산해 Thrust Chamber Size의 Mass flow rates에 산화제·연료·필름 다음으로 표시합니다.
3. 다른 Regen에서 냉각제를 이어받는 구간은 같은 회로로 취급해 외부 냉각제 질량유량을 중복 합산·표시하지 않으며, Engine oxidizer/fuel 회로는 기존 추진제 항목에 이미 포함되므로 별도 표시하지 않습니다.
4. Chamber & Rao geometry의 최상단에 `Dc / Dt / De` 직경 행을 추가하고, 기존 `Rc / Rt / Re` 반지름 행과 동일한 3열 구조로 정렬했습니다.
5. 100% 초과 Regen 유량, 독립/연결/추진제 회로 구분, 외부 냉각제 결과 카드 순서 및 직경 결과에 대한 회귀 테스트를 추가했습니다.

## 0.9.0 — 2026-07-20 20:27:40 KST

1. RPA 4 매뉴얼, 설치된 RPA 표준판의 shifting-equilibrium 최적화 실행 및 solver export를 대조해, 산화제 과잉계수로 조성을 바꾸며 configured nozzle exit의 ideal vacuum specific impulse가 최대인 O/F를 찾는 관측 동작을 확인했습니다.
2. 자동 O/F 탐색을 RPA의 정의와 같이 `α=(O/F)/(O/F)stoich`인 산화제 과잉계수 기반으로 보강하고, RocketCEA에서 화학양론 O/F와 후보별 목적함수를 동일 CEA 객체로 계산하도록 했습니다.
3. 노즐 출구를 외압으로 정의한 경우 후보 O/F마다 같은 출구압에 대응하는 `Ae/At`를 다시 계산하고, 선택한 O/F의 최종 해석도 같은 RocketCEA 출구압 해법을 사용하도록 통일했습니다. RPA가 공개하지 않은 탐색 범위·정련·허용값은 LPA의 bounded scan/golden-section 구현으로 명시적으로 구분했습니다.
4. Input 페이지의 섹션 옆 설명, 입력 hint, 정적 안내·경고 문구를 제거하되 입력 검증 오류와 세그먼트 연결/중첩 상태 같은 기능성 피드백은 유지했습니다.
5. 페이지 제목, 섹션 제목, 입력 필드명, 단위와 결과 LabelFrame의 폰트 크기·굵기를 계층별 공통 스타일로 통일했습니다.
6. `Ambient Condition Performance` 결과 탭을 추가하고, 입력 외압별 고정 하드웨어 성능과 U.S. Standard Atmosphere 1976의 균일 고도별 압력·온도·밀도·추력·비추력·Cf를 별도 표와 CSV로 제공합니다.
7. 외압 스윕을 Throttled Performance에서 분리하고, 외압 변화 시 CEA를 반복 호출하지 않으면서 기준점과 동일한 pressure-thrust 계산을 재사용하도록 개선했습니다.
8. Thermodynamics의 Station properties는 13개 고정 행을 모두 표시하므로 내부 세로 스크롤바를 제거하고, 최소 창 높이에서도 아래 그래프가 눌리지 않도록 전체 보고서만 스크롤되게 했습니다.
9. 직접 `Dc`와 명목 추력을 함께 사용하는 자동 O/F는 숨겨진 `Ac/At` 입력을 사용하지 않고 O/F–목 직경–유효 `Ac/At` 결합을 반복 수렴하도록 했습니다.
10. 표준대기 범위 밖의 고정 외압을 경계 고도로 조용히 치환하지 않으며, 범위 입력은 표준대기 모델과 겹치는 구간만 고도 표로 생성하도록 했습니다.
11. 표준대기 기준점/역변환·유효범위, O/F 조성 변수·경계 판정·외압 출구 통합, 새 결과 페이지와 설명 제거·타이포그래피에 대한 회귀 검증을 추가했습니다.

## 0.8.0 — 2026-07-20 16:28:29 KST

1. Characteristic length 정의를 기존 원통부 단독 체적에서 `L* = (Vcyl + Vconv) / At`로 변경했습니다.
2. 수축부 체적은 현재 원호–직선–원호 contour의 회전체 체적을 계산해 반영하며, L* 입력 모드에서는 이 체적을 제외한 나머지로 원통부 길이 `Lcyl`을 역산합니다.
3. 직접 `Lc/Lcyl` 지정 모드의 결과 L*도 원통부와 실제 축방향 스케일이 적용된 수축부 체적을 모두 포함하도록 통일했습니다.
4. 지정 L*가 선택 형상의 수축부 체적만으로 필요한 최소값 이하이면 음수 또는 0 길이 원통부를 만들지 않고 명확한 입력 오류를 표시합니다.
5. contour metadata에 원통부·수축부·전체 연소실 체적과 해석된 L* 및 `cylinder_plus_converging_section` 체적 규약을 기록합니다.

## 0.7.0 — 2026-07-14 07:29:14 KST

1. Thrust Chamber Size의 `Chamber & Rao geometry`를 `Rc/Rt/Re`, `Lcyl/Lc/Le`, `R1/R2/Rn`, `b/Tn/Te`, `Ac/At/Ae/At/L*` 순서의 3열 × 5행으로 재구성했습니다.
2. 수축각 `b`와 직접 길이 지정 모드에서 수축부를 제외한 원통부 체적 기준의 `L*`를 결과 데이터에 추가했습니다.
3. RPA 4 매뉴얼, 공식 RPA 4.0.13 및 NASA SP-125를 대조해 Tn/Te의 기호와 형상 구성은 같지만 LPA 자동 경험식은 RPA의 비공개 자동 선택 로직과 수치적으로 동일하지 않음을 확인했습니다.
4. Bell contour 결과 metadata에 각도 출처 `rao_angle_method=lpa_empirical_approximation_not_rpa`를 기록하고 별도 검증 문서를 추가했습니다.
5. RocketCEA가 공백 또는 한글 사용자 프로필을 `C:\UserData`로 우회해 일반 사용자 권한에서 실패할 수 있던 문제를 수정했습니다. 실제 데이터는 원래 사용자 프로필에 두고 관리자 권한 없는 안전한 경로 별칭을 사용합니다.
6. 공백·한글 사용자 프로필에서 실제 RocketCEA 계산을 수행하는 회귀 테스트를 추가하고 단일 EXE의 Python/Tk/수치 라이브러리/CEA 데이터 및 네이티브 DLL 포함 상태를 점검했습니다.
7. 단일 EXE에 RocketCEA가 첫 Fortran 계산 전에 요구하는 초기 `f.out` 템플릿을 필수 포함해, 새 PC에서 CEA 시작 직후 프로세스가 종료되는 패키징 결함을 수정했습니다.

## 0.6.1 — 2026-07-14 06:25:09 KST

1. VS Code Code Runner의 Stop 또는 터미널 `Ctrl+C`가 Tk mainloop를 중단할 때 `KeyboardInterrupt` traceback을 표시하지 않고 조용히 종료하도록 했습니다.
2. 정상 창 닫기와 외부 인터럽트가 동일한 멱등 종료 경로를 사용해 분석 executor와 Tk 창을 정확히 한 번 정리하도록 보강했습니다.

## 0.6.0 — 2026-07-13 11:59:18 KST

1. Regen의 Channel occupied angle 입력으로부터 `a1/a min/a2` 채널 폭과 `b1/b min/b2` 리브 폭을 계산해 Thermal Analysis 결과표에 mm 단위로 표시합니다.
2. Thermal Analysis 결과의 `Smooth curves` 기본값을 해제 상태로 변경했습니다.
3. 온도/contour 그래프 아래에 양 끝점을 포함한 최대 30개 대표 station의 축방향 위치, 열유속, `Twg/Twi/Twc/Tc`, 냉각제 압력 `pc`, 속도 `wc`, 밀도 `rho` 표를 추가했습니다.
4. Regen의 Name/Start/End를 한 줄로 배치하고 Wall material 아래의 불필요한 reference 안내 문구를 제거했습니다.
5. Regen 채널 형상 입력을 Width definition·occupied angle·channel count, channel 폭 3점, rib 폭 3점 순서의 세 행으로 재배치했습니다.
6. Surface roughness를 Regen 대화상자 맨 아래로 옮기고 roughness/TBC 세부 입력은 Enable일 때만 표시하도록 변경했습니다.
7. Film의 기본 분사 위치를 `Injector Face (0 mm)`로 바꾸고 Name/Injection position/Specified location을 한 줄로 배치했습니다.
8. Thrust Chamber Size의 Performance와 Mass Flow Rates를 같은 행에 배치하고 모든 metric tile의 크기와 간격을 통일했습니다.
9. Gas residence time을 Performance로 이동하고 chamber pressure와 nozzle exit pressure를 추가했습니다.
10. 좌측 navigation의 `LPA / PROPULSION ANALYSIS` 앞에 있던 내부 이미지 로고를 제거하되 Windows 창·작업표시줄·자식 대화상자 아이콘은 유지했습니다.
11. Windows PowerShell 5.1/PowerShell 7 모두에서 EXE 빌드 사전검사 Python 코드가 따옴표 손실 없이 실행되도록 빌드 스크립트를 보강했습니다.

## 0.5.0 — 2026-07-12 21:44:05 KST

1. Film이 Regen 출구 온도를 받도록 선택하면 Film coolant 종류도 해당 Regen 회로의 유효 냉각제/추진제로 자동 동기화되도록 했습니다.
2. Film 분사 위치에 `Injector Face`를 추가하고 contour 시작점인 0 mm로 해석하도록 했습니다.
3. Thermal Analysis 온도 그래프의 y축을 항상 0 K에서 시작하도록 변경했습니다. 상단은 결과 온도에 맞게 자동 조정되며, contour의 1:1 축척은 유지됩니다.

## 0.4.0 — 2026-07-12 21:10:36 KST

1. Thermal Analysis의 Regen 회로 요약표에 각 회로의 추진제 종류를 함께 표시합니다.
2. 온도 곡선과 상반면 contour의 x축을 하나의 그래프 영역에서 공유하고, contour는 하단에 1:1 축척으로 배치했습니다.
3. breadcrumb 제거 후 남은 빈 공간으로 탭 설명을 옮겨 페이지 상단의 수직 공간을 줄였습니다.
4. Thrust Chamber의 Flow & performance model에서 고정 설정인 `Nozzle flow effect: Multiphase flow with phase-transition effects` 문구를 제거했습니다.
5. Operating envelopes 섹션을 Contour geometry 다음, Thrust Chamber 탭의 맨 하단으로 옮겼습니다.
6. 수축부 크기를 Contraction area ratio 또는 연소실 직경 `Dc`로 직접 지정할 수 있도록 선택 기능을 추가했습니다.
7. 선택 상태에서 깨질 수 있는 좌측 결과 탭의 Unicode 기호를 안정적인 ASCII 숫자 접두어로 교체했습니다.

## 0.3.0 — 2026-07-12 07:55:40 KST

1. 메인 창 제목을 프로젝트 이름·수정 표시 없이 `LPA 0.3.0`으로 고정했습니다.
2. 좌측 탐색과 중복되던 페이지 상단 breadcrumb과 제목 영역을 제거했습니다.
3. Thermal Analysis의 연소기 contour를 상반면만 실제 축척으로 표시하고 형상이 보이지 않던 문제를 수정했습니다.
4. Thermal Analysis의 Regen 회로 요약표에 입구 압력, 출구 압력, 차압을 추가했습니다.
5. Engine Definition에 최고 비추력 기준의 최적 혼합비를 자동 탐색·적용하는 선택 기능을 추가했습니다.
6. Thrust Chamber Size 결과 하단에 주요 치수와 기호를 표시하는 Rao 작도 이미지를 추가했습니다.
7. `Apply film cooling as BLC` 선택의 기본값을 해제 상태로 변경했습니다.

## 0.2.0 — 2026-07-12 06:57:09 KST

1. Engine Definition 페이지가 내용보다 위로 과도하게 스크롤되는 동작을 수정했습니다.
2. 콤보박스 위에서 마우스 휠을 굴릴 때 드롭다운 값이 뜻하지 않게 바뀌지 않도록 했습니다.
3. 스크롤바를 전체 GUI 색상과 형태에 맞게 현대화했습니다.
4. 메뉴 탐색 버튼의 hover 상태에서 글자 대비가 유지되도록 색상을 개선했습니다.
5. 프로그램 버전과 변경 일시를 변경 이력에 기록하는 체계를 추가했습니다.
6. 창 제목에 LPA 버전을 표시하고 Windows 작업표시줄 앱 ID와 아이콘 처리를 보강했습니다.
7. Regen 등 자식 대화상자에서도 LPA 로고 아이콘을 사용할 수 있도록 공통 아이콘 적용 경로를 제공했습니다.
8. Thermal Analysis의 연소기 contour가 실제 종횡비로 보이도록 축 스케일을 통일했습니다.
9. 체크박스의 선택 표시와 상태별 가독성을 개선했습니다.
10. Regen coolant source에서 산화제 또는 연료를 선택하면 coolant 종류와 상대 유량을 자동 산정하도록 했습니다.
11. Regen/Radiation 범위를 Start의 TOP·Conv Boundary·직접 입력 및 End의 Conv Boundary·Bottom·직접 입력 방식으로 명확히 구분했습니다.
12. Thermal Analysis 결과에 Regen별 coolant 입·출구 온도와 최대 내벽 온도 요약표를 추가했습니다.
13. 둘 이상의 Regen 회로를 독립적으로 계산하고 Regen 영역 중첩을 허용하지 않도록 했습니다.
14. 기본 프로젝트 저장 확장자를 `.cfg`로 바꾸고 기존 `.lpa.json`/`.json` 불러오기 호환을 유지했습니다.
15. Thermal Analysis의 Maximum solver iterations 기본값을 200으로 높였습니다.
16. Thrust Chamber Size 결과의 film BLC 적용 여부를 하나의 체크버튼으로 전환할 수 있도록 했습니다.
17. 한 결과 화면의 모든 추력을 최대 추력 기준으로 N 또는 kN 중 하나의 단위로 통일했습니다.
18. Injector부터 Throat까지의 연소가스 잔류시간을 ms 단위로 계산해 표시합니다.
19. 추력·비추력의 중복 film 상태 문구와 Mass Flow Rates의 `nominal point` 보조 문구를 제거했습니다.

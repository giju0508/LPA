# LPA - LGJ Propulsion Analysis · Beta

LPA는 액체로켓 연소기의 성능, 추력실 형상, 열역학 상태와 정상상태 열전달을 예비 설계 단계에서 계산하는 Windows 데스크톱 도구입니다. RPA와 유사한 좌측 입력/결과 탐색 구조를 사용하며, 추진 성능은 RocketCEA, 고온가스측 열전달은 Bartz 상관식을 기본으로 합니다.

현재 버전: **0.16.0b1** · **Beta 사전 배포판** · [변경 이력](CHANGELOG.md) · [검증 기록](docs/VALIDATION.md)

이 버전은 순수유체 포화 2상 재생냉각 경로를 추가한 **Beta**입니다. 구현된 상관식, 계산이 완료된 범위와 수치 수렴 여부를 확인할 수 있지만, 전체 엔진이나 실제 채널의 열전달·CHF·dryout·수명 검증이 완료된 버전은 아닙니다. 특히 증기 질량분율 0.7 제한은 계산 보호 경계이며 실제 dryout 발생점을 뜻하지 않습니다. 물리 적용 상태와 중단 이유를 함께 확인하십시오.

배포 태그: [v0.16.0b1](https://github.com/giju0508/LPA/releases/tag/v0.16.0b1). 소스, 실행 파일 및 시험·빌드 결과의 버전이 같은지 확인하십시오. 이번 변경의 근거·실행 기록은 [열전달 Beta 구현 기록](docs/THERMAL_BETA_2026-10-19.md), [가스측 RPA 비교](docs/THERMAL_GAS_METHOD_2026-10-19.md), [물성 검증](docs/COOLANT_PROPERTIES_2026-10-19.md), [2상 결과 UI 기록](docs/TWO_PHASE_UI_2026-10-19.md)에 있습니다. 이전 [배포 검토](docs/RELEASE_REMEDIATION_2026-10-11.md)와 [자동 O/F 검토](docs/OF_OPTIMIZATION_REVIEW_2026-10-11.md)도 보존합니다.

기능, 해석 로직 또는 주요 GUI가 변경되는 릴리스마다 `lpa.__version__`을 올리고 같은 버전의 변경 내용과 KST 일시를 `CHANGELOG.md`에 기록합니다. README와 Windows FileVersion/ProductVersion 문자열을 일치시키며, 이 Beta의 Windows 고정 버전은 `0.16.0.1`, prerelease flag는 `0x2`입니다. 빌드·회귀시험 출력은 `tmp/build-<version>.log`, `tmp/test-<version>.log`에 남기고 실행 파일·버전별 ZIP의 SHA-256 및 실제 수행한 검증 결과를 `docs/VALIDATION.md`에 기록합니다.

> **중요:** LPA의 결과는 개념/예비 설계 및 비교 검토용입니다. 시험, 상세 CFD/FEA, 구조·피로·수명 해석, 제작 공정 검증, 독립적인 수계산과 전문 엔지니어의 검토를 대체하지 않으며 비행·시험 안전 인증 자료로 사용할 수 없습니다.

## 소스에서 실행

Windows 10/11 64-bit와 python.org의 64-bit CPython 3.14가 필요합니다. `tkinter`는 Python Windows 설치 프로그램에 포함되므로 설치할 때 **Tcl/Tk and IDLE**을 제외하지 마십시오.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --requirement requirements.txt
.\.venv\Scripts\python.exe main.py
```

RocketCEA가 로드되지 않거나 계산에 실패하면 LPA는 화면의 backend/warning에 이를 표시하고 검증 범위가 제한된 이상기체 screening 추정값으로 폴백할 수 있습니다. 폴백을 보수적 추정으로 취급하지 마십시오. 배포 결과를 검증할 때는 backend뿐 아니라 전체 경고와 물리 적용범위를 확인하십시오.

런타임 의존성은 `requirements.txt`에 고정합니다. 주요 계산 패키지는 RocketCEA 1.2.3, CoolProp 8.0.0, `ht` 1.2.0, `fluids` 1.3.1입니다. 기본 물성 backend는 **CoolProp native HEOS**입니다. 선택적 **REFPROP**는 사용자가 별도로 설치하고 유효한 사용권 및 유체 데이터를 준비해야 하며, LPA 소스/EXE에 REFPROP 라이브러리나 유체 파일을 포함하지 않습니다. REFPROP 선택 자체가 모든 유체의 온도·압력 범위나 transport 및 열전달 모델의 적용성을 보장하지 않습니다.

## 기본 사용 흐름과 프로젝트 저장

1. 왼쪽 **INPUT**의 `Engine Definition`, `Thrust Chamber`, `Thermal Analysis`를 순서대로 입력합니다.
2. 상단 **Run Analysis** 또는 `F5`를 누릅니다.
3. 왼쪽 **RESULTS**에서 형상/성능, 열 해석, 열역학 표·그래프, throttled performance와 ambient-condition performance를 확인합니다.
4. `File > Save As` 또는 `Ctrl+Shift+S`로 저장합니다. 프로젝트는 사람이 읽을 수 있는 UTF-8 JSON 형식의 `*.cfg` 파일이며, `File > Open` 또는 `Ctrl+O`로 다시 엽니다. 이전 버전의 `*.lpa.json` 및 일반 `*.json` 프로젝트도 계속 불러올 수 있습니다.

저장 파일은 입력과 열 세그먼트 정의를 보존하지만, 현재 분석 결과의 영구 보고서가 아닙니다. 입력이나 프로그램 버전이 바뀌면 다시 해석하십시오.

Engine Definition에서 H2O2, Ethanol, IPA를 선택하면 별도의 `Mass fraction` 입력란에 질량 백분율을 지정합니다(`0 < wt% ≤ 100`, 소수점 허용). 나머지는 액체 물이며, O/F는 물을 포함한 산화제 공급류/연료 공급류의 질량비입니다. 기존 농도별 H2O2/Ethanol 프로젝트는 이름과 질량분율로 자동 변환됩니다. LNG는 상용 천연가스의 대표 조성(CH4 94%, C2H6 4.7%, C3H8 0.8%, 부탄 0.2%, N2 0.3%, 몰 기준)을 질량 기준으로 변환한 액체 연료 모델입니다. 전체 추진제의 상태·CEA 카드·물성 출처와 근사 범위는 [추진제 검토 기록](docs/PROPELLANT_AUDIT.md)에 정리했습니다.

`Automatically optimize O/F (maximum theoretical vacuum Isp)`는 현재 추진제 조성·공급 상태, 연소실 압력, 수축비, 노즐 출구조건과 shifting/throat-frozen 모델에서 **이론 진공 비추력이 최대**인 O/F를 탐색합니다. 고정 확장비는 모든 후보에 같은 `Ae/At`를 적용하며, 출구압 지정은 후보 O/F마다 해당 압력을 만족하는 `Ae/At`를 계산합니다. 반응효율·노즐 손실·Film·운전 외압을 적용한 delivered Isp는 목적함수에 포함하지 않습니다. 직접 `Dc`와 명목 추력을 함께 지정하면 O/F와 `Ac/At`의 결합이 수렴할 때까지 반복하므로 사이징 조건이 간접적으로 영향을 줄 수 있습니다. 입력 변경과 분석 실행 시 자동값을 갱신하며, 재생냉각 공급 피드백에서도 매 반복의 반응물 상태로 다시 최적화합니다. 조성과 자동 선택 여부를 `*.cfg`에 저장하며 분석 결과에는 실제 적용 O/F와 목적함수·이론 Isp·계산 출처를 기록합니다. RocketCEA를 사용할 수 없으면 같은 진공 Isp 목적의 공학적 fallback임을 경고합니다.

시작 및 New Project의 `LPA Demonstrator` 기본값은 **추력 2000 N @ 1 atm, Pc 20 bar(a), Ac/At 6.25, L* 1200 mm, O/F 1.3, LOX / Ethanol 70 wt%**입니다. 자동 O/F는 해제 상태로 시작합니다. 공급 온도·압력은 선택 입력이며, 입력하면 EOS의 상대 엔탈피 변화가 CEA 카드에 적용됩니다. 둘 다 비우면 기존 CEA 기준 상태를 사용하고, 온도만 입력하면 압력 1.01325 bar(LNG 5 bar), 압력만 입력하면 추진제 기준 온도를 사용합니다. LNG는 공통 111.66 K·5 bar 기준의 혼합물 엔탈피를 사용하고 실제 공급 상태를 지정할 수 있습니다. IPA/H2O2 및 kerosene의 공급 엔탈피는 별도 screening 근사와 경고를 유지합니다.

수치 수렴과 물리 적용범위를 별도로 표시합니다. 냉각제의 압력 의존 EOS와 엔탈피 행진, 리브 fin·원통벽 면적 보정, 사각채널 층류, 연결 Film/Regen 반복을 사용합니다. 지원 범위 안의 순수유체 포화 비등은 아래 Beta 모델로 계산하고, 혼합물 2상 열전달·CHF/dryout·검증되지 않은 초임계 열전달·액체 Film 증발·발열 분해·coking·비정상/ablative 영역은 별도로 진단합니다. `screening`, `unsupported`, `invalid`와 수치 수렴·계산 완료 개수를 함께 확인하며, 수렴만으로 실제 설계 적합성을 판정하지 않습니다.

RPA는 내부 탐색 범위·정련 알고리즘·수렴 허용값을 공개하지 않습니다. LPA는 관측된 목적함수와 출구조건 의미를 따르되, O/F 0.10–30.0의 49점 bounded coarse scan 후 최상 구간을 golden-section 30회로 정련합니다. RocketCEA의 공개 API는 RPA처럼 임의의 pressure-ratio/area-ratio 위치에서 동결시키는 기능을 제공하지 않으므로, 신규 입력은 shifting 또는 throat freezing을 제공합니다. 현재 유한면적 연소기(FAC)에서 chamber freezing은 CEA station 출력이 유효하지 않아 차단하며, 임의 동결 위치는 지원하지 않습니다. 열역학 데이터베이스와 비공개 수치 설정까지 포함한 RPA와의 완전한 수치 일치도 보장하지 않습니다. RocketCEA 계산이 실패하면 engineering fallback을 사용하며 분석 결과 warning에 기록합니다.

Thrust Chamber의 `Contraction definition`은 기존 `Area ratio (Ac/At)` 또는 `Chamber diameter (Dc)`를 선택할 수 있습니다. Dc를 선택하면 원형 단면 관계 `Ac/At = (Dc/Dt)²`로 유효 수축면적비를 계산합니다. 목 직경을 직접 입력한 경우 즉시 결정되며, 명목 추력으로 크기를 정하는 경우에는 RocketCEA 유한면적 연소기 계산과 목 직경이 일치할 때까지 반복합니다. 이전 프로젝트는 자동으로 Ac/At 방식으로 열립니다.

Characteristic length는 `L* = (Vcyl + Vconv) / At`로 계산합니다. `Vcyl`은 원통형 연소실 체적, `Vconv`는 실제 수축 형상의 회전체 체적입니다. 직접 Lc/Lcyl은 길이를 우선하여 타원호를 만들 수 있으며, 결과에는 실제 수축각과 끝점 곡률반경 및 요청값과의 차이를 표시합니다. L* 입력 모드에서는 지정 체적에서 수축부 체적을 제외한 나머지로 `Lcyl`을 역산하며, 직접 길이 모드의 결과 L*에도 두 체적을 모두 포함합니다.

Ambient Condition Performance는 입력한 외압 점의 고정 하드웨어 성능과, 같은 외압 범위에 대응하는 균일 고도 점의 성능을 별도 표로 제공합니다. 고도·온도·밀도·압력 변환은 [U.S. Standard Atmosphere 1976](https://ntrs.nasa.gov/citations/19770009539)의 층별 geopotential-altitude 모델을 사용하며, 구현 범위는 기하 고도 -5 km부터 약 86 km입니다. 진공이나 모델 범위 밖의 외압은 외압 표에는 유지되지만 유한한 표준대기 등가고도로 표시하지 않으며, 고도 표는 요청 외압 범위와 모델 유효 범위의 교집합만 제공합니다.

## 열 해석과 Cooling segments

`Enable thermal analysis`를 켠 뒤 `+ Regen`, `+ Film`, `+ Radiation`으로 세그먼트를 추가합니다.

- Regen/Radiation의 Start는 `TOP`, `Conv Boundary`, `Specified location` 중에서, End는 `Conv Boundary`, `BOTTOM`, `Specified location` 중에서 선택합니다. 직접 위치를 선택한 경우에만 mm 입력란이 활성화됩니다.
- Regen끼리 또는 Regen과 Radiation의 축방향 범위가 겹치면 실행 전에 오류로 처리됩니다. 경계점만 맞닿은 인접 세그먼트는 허용됩니다.
- Regen coolant는 엔진 산화제, 엔진 연료, 사용자 지정 coolant 또는 다른 Regen 세그먼트에서 선택할 수 있습니다. 엔진 유체를 선택하면 추진제 종류와 혼합비에 따른 상대 유량이 자동으로 정해집니다. 다른 Regen을 참조한 뒤 원본을 지우면 연결이 끊긴 상태로 표시되므로 새 소스를 지정해야 합니다.
- Regen별 입구·출구 압력과 차압은 국부 채널 형상, 냉각제 상태 및 contour 경로 길이로 적분합니다. 단상은 거칠기를 반영한 Darcy–Weisbach, 지원되는 2상은 Lockhart–Martinelli 마찰과 homogeneous equilibrium model(HEM) 가속 압력손실을 사용합니다. 2상 마찰 모델은 평활 채널 근사이며, 중력·매니폴드·벤드·입출구·공급 배관의 국부 손실은 포함하지 않습니다.
- Thermal Analysis 결과표는 Regen별 유효 냉각제/추진제 종류, 입·출구 상태와 채널/리브 폭을 표시하며 연결된 Regen은 원본 회로의 냉각제 종류를 이어받습니다. 온도 곡선과 상반부 contour는 같은 x 좌표 변환을 공유하고 contour의 x/y는 1:1 실제축척을 유지합니다. 그래프 아래 축방향 표는 약 30개 대표 station의 열유속, 벽/냉각제 온도, 냉각제 압력·속도·밀도·증기 질량분율·유동/비등 상태를 보여 줍니다.
- Film은 Injector Face(0 mm), 실린더 연소실/수축부 경계 또는 지정 x 위치에 배치할 수 있습니다. Regen 출구 온도를 받는 경우 Film coolant도 해당 Regen의 유효 냉각제/추진제로 자동 동기화됩니다. Film 성능 보정은 경계층 냉각(BLC)의 단순 운동량 회수 모델입니다.
- 계산 밀도는 Low **120**, Medium **300**(기본), High **700**개 축방향 station입니다. 실제 개수는 Thermal Analysis 결과에 함께 표시됩니다. 격자 독립성이 필요한 설계 판단은 세 단계 결과를 비교하십시오.

### 포화 2상 재생냉각의 Beta 범위

기본 `auto`는 순수유체의 포화 2상 상태에서 수력직경 `Dh`에 따라 상관식을 선택합니다. 선택된 모델, 출처와 중단 이유는 결과의 모델 진단에 기록합니다.

화면에서는 `Auto (Beta)` 또는 `Disabled`를 선택합니다. 개별 상관식 직접 선택과 건도 상한 조정은 현재 Python API의 `ThermalSolverSettings`에서 제공합니다.

| 선택 | 수력직경 범위 | 계산 범위 |
|---|---|---|
| `auto` → Li–Wu (2010) | 0.19 ≤ Dh ≤ 3.1 mm | 미니채널 포화 비등 대류의 screening 추정 |
| `auto` → Chen–Bennett (1980) | 3.1 < Dh ≤ 32 mm | 통상 크기 관의 포화 비등 대류; 액상 기준 Reynolds 수 제한 적용 |
| Chen–Bennett 직접 선택 | 3 ≤ Dh ≤ 32 mm | 위와 같은 제한; 3.0–3.1 mm 중첩 범위에서 선택 가능 |
| `disabled` | 해당 없음 | 2상 상태를 보고하고 해당 열전달 계산 중단 |

이 경로는 **pre-dryout을 가정한 순수유체 포화 비등**에 한정됩니다. 사각채널을 수력직경으로 대응시키는 방법, slip/유동양식, 극저온 유체별 적용성은 실제 채널 시험으로 검증해야 합니다. 액상·기상 포화 transport와 표면장력·잠열이 필요하며, 압력이 임계압력의 0.8배 이상이거나 상관식의 직경·Reynolds 수 등 조건을 벗어나면 지원하지 않습니다. 열전달 모델의 전체 검증이 끝났다는 뜻으로 `Beta` 또는 `screening` 상태를 해석하지 마십시오.

최대 증기 **질량**분율은 기본 0.7이며 이 이하로 제한할 수 있습니다. **0.7은 실제 dryout 품질이나 안전 여유가 아닙니다.** CHF, dryout 발생 위치, post-dryout 열전달과 2상 유동 불안정은 예측하지 않습니다. Bulk가 액체인데 냉각제측 벽이 포화온도를 넘는 subcooled-boiling 영역도 별도 모델 부재를 진단합니다.

실행 진단은 `%LOCALAPPDATA%/LPA/logs/lpa.log`에 회전 저장됩니다. 버전, Regen 입·출구 상태·질량건도·완료 구간 수와 적용범위/중단 이유를 기록하며, 계산 수치와 원본 station은 결과의 진단·CSV에서도 확인할 수 있습니다.

에탄올/물·LNG 등의 혼합물은 EOS가 제공하는 범위에서 2상 상태와 질량분율을 검출·표시하지만, temperature glide와 성분간 물질전달을 반영하는 혼합물 비등 상관식이 없으므로 **2상 열전달 행진을 중단**합니다. 물성 backend의 선택이나 압력 증가만으로 이 제한이 해제되지는 않습니다.

### 결과의 수렴·완료·중단 해석

온도 그래프의 황색 음영/사선과 `Two-phase coolant` 범례는 보고된 2상 영역을 표시합니다. 서로 떨어진 영역과 서로 다른 세그먼트는 분리하며, 모델 밖 첫 station에 상태만 알려진 경우에도 음영은 나타날 수 있습니다. 음영이 있는 station 모두에 벽온도 예측값이 존재하는 것은 아닙니다.

`Numerically converged`는 계산된 station의 비선형 반복 수렴 여부입니다. **`Solved wall stations n/N · Unsolved m`**는 실제 벽온도를 얻은 개수이며 전체 구간 계산 여부를 별도로 확인합니다. 미계산 온도는 NaN/공란으로 남깁니다. 물성/EOS 실패, 공급압 소진, 비등 모델의 적용범위 밖 상태에서는 부분 결과와 중단 이유를 확인하십시오. 중간에서 멈춘 결과의 최고 벽온도를 전체 엔진 최고온도로 간주하지 마십시오.

`Export all stations…`는 smoothing과 대표 행 샘플링을 적용하지 않은 전체 CSV를 저장합니다. 증기 질량분율(0–1), `coolant_flow_regime`, `wall_solution_available`, 수치/물리 상태, 경고와 모델/물성 출처를 함께 내보냅니다. 진단창에서도 계산 완료 개수·질량분율 범위·비등 상태와 선택한 2상 모델의 근거를 확인할 수 있습니다.

열전도도 재료 표는 온도 사이를 선형 보간하고 표 범위 밖에서는 끝값으로 clamp하고 범위 초과를 결과에 경고합니다. CuCrZr는 LPBF direct-aged 측정 anchor(`doi:10.1016/j.matchar.2024.114103`)와 rounded screening curve, AlSi10Mg는 LPBF 100 W/0.2 m/s의 100-400 °C 곡선(`doi:10.3390/ma16144920`, Fig. 2f)을 사용합니다. IN625/IN718은 Special Metals SMC-063/SMC-045, Ti64는 NASA-TM-101660, C103은 ASM Alloy Digest Cb-25가 근거입니다. 모두 온도 보간용 공학 데이터이지 설계 허용치가 아니며, 특히 CuCrZr와 AlSi10Mg 곡선은 **screening-only**입니다. 실제 적층 방향, 열처리, 재료 lot, 코팅 계면과 사용 온도 범위에 맞는 시험 데이터로 교체·검증해야 합니다.

## 단일 EXE 빌드

아래 스크립트는 별도 `.venv-build`를 만들고 고정된 의존성을 설치한 뒤 `dist\LPA.exe` 한 파일을 생성합니다.

```powershell
PowerShell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

의존성이 이미 설치된 동일 build venv를 재사용할 때만 `-SkipInstall`을 지정할 수 있습니다. `LPA.spec`은 Python 3.14, Tcl/Tk, NumPy·Matplotlib·SciPy, Windows 아이콘, Rao 참고 이미지, CoolProp HEOS, `ht`·`fluids`, RocketCEA의 `py_cea` Fortran 확장과 `f.inp`, 초기 `f.out`, `temp.dat`, `thermo.lib`, `trans.lib`를 단일 EXE에 포함하는 구성입니다. SciPy는 초임계 유체의 isobaric Cp peak 진단에도 사용합니다. 지원 대상은 **64-bit Windows 10/11**이며 Python·pip·개발 도구를 별도 설치하지 않는 실행 파일 배포를 목표로 합니다. 실제 버전의 빌드·실행 시험과 해시는 [검증 기록](docs/VALIDATION.md)을 확인하십시오. REFPROP의 외부 라이브러리·유체 데이터·사용권은 포함하지 않습니다.

One-file EXE는 시작할 때 `%TEMP%` 아래에 번들 런타임을 풀므로 해당 위치의 쓰기·실행 권한이 필요합니다. RocketCEA는 `%USERPROFILE%\RocketCEA\lpa-run-<PID>-<ID>`에 실행별 작업 파일을 만들어 동시 실행의 충돌을 방지합니다. 종료 시 해당 실행 폴더만 정리하며, 네이티브 파일 잠금으로 정리할 수 없는 경우 그 폴더를 남깁니다. 공백이나 한글이 포함된 사용자 프로필은 관리자 권한이 필요 없는 임시 경로 별칭을 사용하며 실제 파일은 원래 프로필에 유지됩니다. 서명하지 않은 사내/개인 빌드는 Windows SmartScreen 또는 백신의 평판 경고가 나타날 수 있으므로 배포본은 코드 서명과 조직 표준 보안 검사를 권장합니다.

배포 시험은 [검증 체크리스트](docs/VALIDATION.md)의 실제 수행 기록과 구분하여 관리합니다. 코드 회귀시험이나 상관식 수치 대조의 통과가 깨끗한 대상 PC/VM 시험, 코드 서명·악성코드 검사 또는 전체 엔진의 실험 검증을 대신하지 않습니다. RocketCEA는 GPL-3 라이선스 구성요소이므로 바이너리 재배포 전 해당 라이선스 의무도 확인해야 합니다.

## 계산 근거와 범위

아래 페이지는 **첨부 PDF에 표시된 페이지 번호** 기준이며, LPA가 동일한 상용 RPA의 완전한 재현이라는 뜻은 아닙니다.

- `RPA_LiquidRocketEngineAnalysis_II.pdf` pp. 4-17: 화학평형/동결 유동의 열역학 관계, 노즐 상태와 이론 로켓 성능. pp. 18-22: 입력·출력 항목과 NASA CEA2 비교 예제.
- `RPA_ThermalAnalysis.pdf` p. 7: Bartz 열전달 상관식. pp. 8-11: 경계층/Film 냉각. pp. 11-18: 복사 및 재생냉각의 정상상태 열수지·채널 관계. p. 19: TBC. pp. 21-22: RPA 입력 및 `Twg`, `Twi`, `Twc`, `Tc` 결과 정의.
- `RPA_4_User_Manual.pdf` p. 12: O/F, 산화제 과잉계수와 maximum-specific-impulse optimum mixture ratio. pp. 12-19: 엔진/노즐/스로틀/추력실 입력 구조. pp. 20-29: 열전달 설정, Cooling segments, Regen/Film/Radiation과 TBC. pp. 30-45: 열역학, 성능, altitude/throttled performance, 추력실 형상과 열 해석 결과 화면.
- 2상 Beta 구현: Li–Wu (2010, `doi:10.1016/j.ijheatmasstransfer.2010.01.012`), Chen–Bennett (1980, `doi:10.1002/aic.690260317`), Lockhart–Martinelli/Chisholm(`doi:10.1016/0017-9310(67)90047-6`)의 `ht`·`fluids` 구현을 사용합니다. HEM 가속 압력손실과 사각채널 대응은 별도 모델 가정이며, 상관식 구현 대조와 하드웨어 검증은 다른 항목입니다.

Rao bell은 두 각도 입력칸을 비우면 확장비가 5–50 밖이어도 Tn/Te를 자동 선택합니다. `Ae/At=5–50`, `Le/Lc15=60–100%`의 NASA SP-125 도표 안에서는 기존 보간을 유지하며, 밖에서는 실제 RPA 공식 스크립트 출력 20개와 대조한 Prandtl–Meyer 및 출구 유동 관계식을 사용합니다. RocketCEA의 출구 Mach 수와 목·출구 등엔트로피 지수를 적용하며, RPA를 별도로 설치하지 않아도 LPA 단일 EXE에서 계산됩니다. 자동 각도가 지정한 길이·목 원호와 양립하지 않으면 작도 전에 각도를 조정하고 보정 전후 값과 경고를 기록합니다. 길이와 원호 반경은 유지하며, 해당 치수로 유효한 형상 자체가 불가능하면 입력 오류로 표시합니다. 직접 각도 입력도 계속 지원합니다. 도표 판독 근사, NASA/RPA 선택 경계의 전환 특성과 두 프로그램의 열역학 차이는 [Rao contour verification](docs/RAO_CONTOUR.md)에 기록했습니다.

LPA의 축방향 열 모델은 정상상태 1-D 벽 전도, 경험 상관식 기반 대류/복사, 압력 의존 냉각제 엔탈피 수지와 국소 CEA 가스 상태를 결합합니다. Bartz는 RPA에 제시된 형태와 sigma 보정을 따르지만, 가스 물성 기준·복사 모델·냉각제 및 채널 모델까지 포함해 상용 RPA와 수치적으로 동일한 열유속을 보장하지 않습니다.

비정상 점화/정지, 국부 3-D 유동, 연소 불안정, 분사기 상세, 채널 manifold 분배, CHF/dryout·post-dryout·2상 유동 불안정, 재료 강도·크리프·피로·산화·수명 및 제작 공차는 해석하지 않습니다. 압력·온도 범위가 넓은 물성 데이터가 있더라도 화학적 분해·coking·구조 안전이나 해당 열전달 상관식의 적용성을 함께 확보한 것은 아닙니다.

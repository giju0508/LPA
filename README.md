# LPA - LGJ Propulsion Analysis

LPA는 액체로켓 연소기의 성능, 추력실 형상, 열역학 상태와 정상상태 열전달을 예비 설계 단계에서 계산하는 Windows 데스크톱 도구입니다. RPA와 유사한 좌측 입력/결과 탐색 구조를 사용하며, 추진 성능은 RocketCEA, 고온가스측 열전달은 Bartz 상관식을 기본으로 합니다.

현재 버전: **0.7.0** · [변경 이력](CHANGELOG.md)

기능, 해석 로직 또는 주요 GUI가 변경되는 릴리스마다 `lpa.__version__`을 올리고, 같은 버전의 변경 내용과 KST 일시를 `CHANGELOG.md`에 기록합니다.

> **중요:** LPA의 결과는 개념/예비 설계 및 비교 검토용입니다. 시험, 상세 CFD/FEA, 구조·피로·수명 해석, 제작 공정 검증, 독립적인 수계산과 전문 엔지니어의 검토를 대체하지 않으며 비행·시험 안전 인증 자료로 사용할 수 없습니다.

## 소스에서 실행

Windows 10/11 64-bit와 python.org의 64-bit CPython 3.14가 필요합니다. `tkinter`는 Python Windows 설치 프로그램에 포함되므로 설치할 때 **Tcl/Tk and IDLE**을 제외하지 마십시오.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --requirement requirements.txt
.\.venv\Scripts\python.exe main.py
```

RocketCEA가 로드되지 않거나 계산에 실패하면 LPA는 화면의 backend/warning에 이를 표시하고 보수적인 이상기체 추정값으로 폴백할 수 있습니다. 배포 결과를 검증할 때는 반드시 `RocketCEA + Bartz`가 표시되는지 확인하십시오.

## 기본 사용 흐름과 프로젝트 저장

1. 왼쪽 **INPUT**의 `Engine Definition`, `Thrust Chamber`, `Thermal Analysis`를 순서대로 입력합니다.
2. 상단 **Run Analysis** 또는 `F5`를 누릅니다.
3. 왼쪽 **RESULTS**에서 형상/성능, 열 해석, 열역학 표·그래프와 throttled performance를 확인합니다.
4. `File > Save As` 또는 `Ctrl+Shift+S`로 저장합니다. 프로젝트는 사람이 읽을 수 있는 UTF-8 JSON 형식의 `*.cfg` 파일이며, `File > Open` 또는 `Ctrl+O`로 다시 엽니다. 이전 버전의 `*.lpa.json` 및 일반 `*.json` 프로젝트도 계속 불러올 수 있습니다.

저장 파일은 입력과 열 세그먼트 정의를 보존하지만, 현재 분석 결과의 영구 보고서가 아닙니다. 입력이나 프로그램 버전이 바뀌면 다시 해석하십시오.

Engine Definition의 `Automatically optimize for maximum vacuum Isp`를 선택하면 현재 추진제, 연소실 압력, 수축비, 노즐 출구조건과 평형/동결 설정을 유지한 채 RocketCEA 진공 비추력이 최대가 되는 O/F를 탐색합니다. 계산된 O/F와 기준 비추력은 화면에 표시되고 `*.cfg`에도 저장됩니다. RocketCEA 계산이 실패한 경우에는 화면에 명시된 engineering fallback을 사용합니다.

Thrust Chamber의 `Contraction definition`은 기존 `Area ratio (Ac/At)` 또는 `Chamber diameter (Dc)`를 선택할 수 있습니다. Dc를 선택하면 원형 단면 관계 `Ac/At = (Dc/Dt)²`로 유효 수축면적비를 계산합니다. 목 직경을 직접 입력한 경우 즉시 결정되며, 명목 추력으로 크기를 정하는 경우에는 RocketCEA 유한면적 연소기 계산과 목 직경이 일치할 때까지 반복합니다. 이전 프로젝트는 자동으로 Ac/At 방식으로 열립니다.

## 열 해석과 Cooling segments

`Enable thermal analysis`를 켠 뒤 `+ Regen`, `+ Film`, `+ Radiation`으로 세그먼트를 추가합니다.

- Regen/Radiation의 Start는 `TOP`, `Conv Boundary`, `Specified location` 중에서, End는 `Conv Boundary`, `BOTTOM`, `Specified location` 중에서 선택합니다. 직접 위치를 선택한 경우에만 mm 입력란이 활성화됩니다.
- Regen끼리 또는 Regen과 Radiation의 축방향 범위가 겹치면 실행 전에 오류로 처리됩니다. 경계점만 맞닿은 인접 세그먼트는 허용됩니다.
- Regen coolant는 엔진 산화제, 엔진 연료, 사용자 지정 coolant 또는 다른 Regen 세그먼트에서 선택할 수 있습니다. 엔진 유체를 선택하면 추진제 종류와 혼합비에 따른 상대 유량이 자동으로 정해집니다. 다른 Regen을 참조한 뒤 원본을 지우면 연결이 끊긴 상태로 표시되므로 새 소스를 지정해야 합니다.
- Regen별 입구·출구 압력과 차압은 국부 채널 형상, 거칠기, 냉각제 상태 및 contour 경로 길이를 이용한 Darcy-Weisbach 분포손실입니다. 매니폴드, 벤드, 입·출구와 공급 배관의 국부 손실은 포함하지 않습니다.
- Thermal Analysis 결과표는 Regen별 유효 냉각제/추진제 종류, 입·출구 상태와 채널/리브 폭을 표시하며, 연결된 Regen은 원본 회로의 냉각제 종류를 이어받습니다. 온도 곡선과 상반부 contour는 동일한 x 좌표 변환을 공유하고 contour의 x/y는 화면 크기와 관계없이 1:1 실제축척을 유지합니다. 그래프 아래 축방향 표는 약 30개 대표 station의 열유속, 벽/냉각제 온도, 냉각제 압력·속도·밀도를 보여 줍니다.
- Film은 Injector Face(0 mm), 실린더 연소실/수축부 경계 또는 지정 x 위치에 배치할 수 있습니다. Regen 출구 온도를 받는 경우 Film coolant도 해당 Regen의 유효 냉각제/추진제로 자동 동기화됩니다. Film 성능 보정은 경계층 냉각(BLC)의 단순 운동량 회수 모델입니다.
- 계산 밀도는 Low **120**, Medium **300**(기본), High **700**개 축방향 station입니다. 실제 개수는 Thermal Analysis 결과에 함께 표시됩니다. 격자 독립성이 필요한 설계 판단은 세 단계 결과를 비교하십시오.

열전도도 재료 표는 온도 사이를 선형 보간하고 표 범위 밖에서는 끝값으로 clamp합니다. CuCrZr는 LPBF direct-aged 측정 anchor(`doi:10.1016/j.matchar.2024.114103`)와 rounded screening curve, AlSi10Mg는 LPBF 100 W/0.2 m/s의 100-400 °C 곡선(`doi:10.3390/ma16144920`, Fig. 2f)을 사용합니다. IN625/IN718은 Special Metals SMC-063/SMC-045, Ti64는 NASA-TM-101660, C103은 ASM Alloy Digest Cb-25가 근거입니다. 모두 온도 보간용 공학 데이터이지 설계 허용치가 아니며, 특히 CuCrZr와 AlSi10Mg 곡선은 **screening-only**입니다. 실제 적층 방향, 열처리, 재료 lot, 코팅 계면과 사용 온도 범위에 맞는 시험 데이터로 교체·검증해야 합니다.

## 단일 EXE 빌드

아래 스크립트는 별도 `.venv-build`를 만들고 고정된 의존성을 설치한 뒤 `dist\LPA.exe` 한 파일을 생성합니다.

```powershell
PowerShell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

의존성이 이미 설치된 동일 build venv를 재사용할 때만 `-SkipInstall`을 지정할 수 있습니다. `LPA.spec`은 Python 3.14 인터프리터, Tcl/Tk, 현재 런타임에서 사용하는 NumPy와 Matplotlib, Windows 아이콘, Rao 형상 참고 이미지, RocketCEA의 `py_cea` Fortran 확장과 `f.inp`, 초기 `f.out`, `temp.dat`, `thermo.lib`, `trans.lib`를 한 파일에 수집합니다. SciPy는 빌드 환경에 고정되어 있지만 현재 LPA 런타임에서 import하지 않으므로 EXE에는 수집하지 않습니다. 따라서 지원 대상인 **64-bit Windows 10/11**에서는 Python, pip, RocketCEA 또는 별도 Python 라이브러리를 설치하지 않고 `LPA.exe`만 실행할 수 있습니다. 다른 운영체제와 32-bit Windows용 바이너리는 아닙니다.

One-file EXE는 시작할 때 `%TEMP%` 아래에 번들 런타임을 풀므로 해당 위치의 쓰기·실행 권한이 필요합니다. RocketCEA는 `%USERPROFILE%\RocketCEA`에 작업 파일을 만듭니다. 공백이나 한글이 포함된 사용자 프로필은 관리자 권한이 필요 없는 임시 경로 별칭을 사용하며 실제 파일은 원래 프로필에 유지됩니다. 서명하지 않은 사내/개인 빌드는 Windows SmartScreen 또는 백신의 평판 경고가 나타날 수 있으므로 배포본은 코드 서명과 조직 표준 보안 검사를 권장합니다.

배포 전에는 [검증 체크리스트](docs/VALIDATION.md)를 모두 통과하고, 대상 PC와 같은 Windows 아키텍처에서 서명·악성코드 검사·오프라인 실행 시험을 별도로 수행하십시오. RocketCEA는 GPL-3 라이선스 구성요소이므로 바이너리 재배포 전 해당 라이선스 의무도 확인해야 합니다.

## 계산 근거와 범위

아래 페이지는 **첨부 PDF에 표시된 페이지 번호** 기준이며, LPA가 동일한 상용 RPA의 완전한 재현이라는 뜻은 아닙니다.

- `RPA_LiquidRocketEngineAnalysis_II.pdf` pp. 4-17: 화학평형/동결 유동의 열역학 관계, 노즐 상태와 이론 로켓 성능. pp. 18-22: 입력·출력 항목과 NASA CEA2 비교 예제.
- `RPA_ThermalAnalysis.pdf` p. 7: Bartz 열전달 상관식. pp. 8-11: 경계층/Film 냉각. pp. 11-18: 복사 및 재생냉각의 정상상태 열수지·채널 관계. p. 19: TBC. pp. 21-22: RPA 입력 및 `Twg`, `Twi`, `Twc`, `Tc` 결과 정의.
- `RPA_4_User_Manual.pdf` pp. 12-19: 엔진/노즐/스로틀/추력실 입력 구조. pp. 20-29: 열전달 설정, Cooling segments, Regen/Film/Radiation과 TBC. pp. 30-45: 열역학, 성능, throttled performance, 추력실 형상과 열 해석 결과 화면.

Rao bell의 Tn/Te 기호와 접선-교점 포물선 구성은 RPA와 같습니다. 다만 RPA 4 매뉴얼은 각도를 생략했을 때의 내부 자동 선택식을 공개하지 않습니다. 공식 RPA 4.0.13을 `Ae/At=14`, `Le/c15=80%`로 대조한 자동값은 Tn 27.291945°, Te 8.0°였고, 현재 LPA 경험식은 Tn 30.520318°, Te 10.629171°이므로 **자동 각도는 RPA와 수치적으로 동일하지 않습니다**. Bell 결과 metadata의 `rao_angle_method`가 이 출처를 표시하며 자세한 검증 경계는 [Rao contour verification](docs/RAO_CONTOUR.md)에 기록했습니다.

LPA의 축방향 열 모델은 정상상태 1-D 벽 전도, 경험 상관식 기반 대류/복사, 단순 coolant 에너지 수지와 준 1-D 가스 상태를 결합합니다. 비정상 점화/정지, 국부 3-D 유동, 연소 불안정, 분사기 상세, 채널 manifold 분배, boiling/two-phase 위기, 재료 강도·크리프·피로·산화·수명 및 제작 공차는 해석하지 않습니다.

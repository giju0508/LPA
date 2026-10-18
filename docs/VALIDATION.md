# LPA 검증 및 배포 체크리스트

이 문서는 소스와 `dist\LPA.exe`의 release 후보를 검증하기 위한 최소 절차입니다. 체크하지 않은 항목은 검증 완료로 간주하지 않습니다. 수치 결과는 예비 설계용이며, 여기의 software test를 통과해도 추진기관의 안전성이나 적합성이 인증되는 것은 아닙니다.

## 기준 환경

- Windows 10/11 64-bit
- CPython 3.14 64-bit, Tk 8.6
- `requirements.txt` 및 `requirements-build.txt`에 고정된 버전
- 네트워크가 차단된 일반 사용자 계정의 깨끗한 대상 PC 또는 VM

## 1. 소스 검증

```powershell
py -3.14 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install --requirement requirements-build.txt
.\.venv-build\Scripts\python.exe -m compileall -q main.py lpa tests
.\.venv-build\Scripts\python.exe -m pytest tests -q
.\.venv-build\Scripts\python.exe -c "compile(open('LPA.spec', encoding='utf-8').read(), 'LPA.spec', 'exec')"
```

Windows Tcl/Tk 시험은 `pytest.ini`의 `--capture=sys`를 사용한다. OS 표준 파일 디스크립터를 교체하는 pytest 기본 FD capture에서는 실제 파일이 있어도 Tcl 초기화/PNG 로딩이 실패하는 문제가 재현되었다. sys capture는 Python 출력의 실패 보고를 유지하며 GUI/이미지 시험을 skip하지 않는다.

- [ ] 모든 명령의 exit code가 0이다.
- [ ] `python main.py` 실행 후 창이 잘리지 않고 1080 x 700 최소 크기에서 각 입력 페이지를 끝까지 스크롤할 수 있다.
- [ ] DPI 100%, 125%, 150%에서 텍스트, combobox, 표 헤더와 Matplotlib toolbar가 겹치거나 잘리지 않는다.
- [ ] 메인 창 제목은 프로젝트 저장·수정 상태와 관계없이 현재 버전의 `LPA <version> Beta`만 표시되고, 탭 제목은 Save/Run 옆 상단 영역에 한 번만 표시된다. LNG 선택 시 적용 조성이 표시되고, 탭 설명은 필요한 경우에만 표시된다.
- [ ] VS Code Code Runner Stop 또는 터미널 `Ctrl+C`로 중단해도 `KeyboardInterrupt` traceback 없이 executor와 Tk 창이 정리된다.
- [ ] 좌측 INPUT/RESULTS 항목의 숫자 접두어가 선택·비선택 상태 및 DPI 100~150%에서 깨지지 않는다.
- [ ] 자동 O/F를 선택하면 입력란이 잠기고 현재 추진제 조성·공급 상태·압력·수축비·노즐 출구조건·동결 모델의 최대 이론 진공 Isp O/F가 적용되며, 해제하면 직접 입력할 수 있다. 출구압 지정은 후보별 확장비를 계산하고, 직접 Dc+명목추력의 결합은 수렴한다. 분석/공급 피드백에서 다시 계산한 O/F와 냉각 유량이 일치한다.
- [ ] H2O2/Ethanol/IPA 선택 시에만 질량분율 입력이 표시된다. 소수점 농도를 저장·재열기하고, 0 이하/100 초과/NaN/무한대 입력을 거부한다. 기존 농도별 프로젝트의 농도와 Regen/Film 연결을 보존한다.
- [ ] 기본 엔진은 2000 N @ 1 atm, Pc 20 bar(a), Ac/At 6.25, L* 1200 mm, O/F 1.3, LOX / Ethanol 70 wt%이며 자동 O/F는 꺼져 있다.

## 2. 기준 수치 확인

동일한 입력 JSON을 보존하고 버전별 결과를 비교합니다. 절대 오차뿐 아니라 계산 backend와 warning도 함께 기록합니다.

- [ ] RocketCEA LOX/RP-1 기준점에서 backend가 `rocketcea + Bartz`이고 c-star, chamber temperature, gamma, sea-level/optimum/vacuum thrust 및 Isp가 유한·양수이다.
- [ ] `RPA_LiquidRocketEngineAnalysis_II.pdf` pp. 20-22의 CEA2 비교 사례 중 재현 가능한 propellant/pressure/mixture-ratio 조합을 별도 fixture로 고정하고, RocketCEA/RPA 정의와 단위 차이를 기록한 허용오차 안에 든다.
- [ ] area-ratio 입력과 ambient-pressure 입력으로 계산한 nozzle exit 조건이 서로 일관되며, throat Mach가 약 1이고 축방향 압력은 유한하다.
- [ ] 직접 Dc와 직접 Dt 조합에서 `Ac/At = (Dc/Dt)²` 및 contour의 Dc가 입력과 일치하며, 명목 추력 기준에서도 반복 계산 후 동일 관계가 성립한다.
- [ ] 0.3.x 이하 프로젝트를 연 뒤 수축부 정의가 기존 Ac/At 방식으로 복원되고 저장·재열기 후 선택 방식과 값이 유지된다.
- [ ] Film 0%일 때 with/without-film 결과가 같고, Film 사용 시 질량 보존(`total = oxidizer + fuel + film`)이 허용오차 안에서 성립한다.
- [ ] throttle/ambient range의 행 수가 입력 points와 같고 양 끝값이 정확히 포함된다.
- [ ] Ambient Condition Performance의 외압 표와 표준대기 고도 표가 Throttled Performance와 분리되고, 고도 표는 U.S. Standard Atmosphere 1976의 -5~약 86 km 범위에서 압력·온도·밀도를 일관되게 표시한다.
- [ ] Thermodynamics Station properties의 13개 행이 모두 보이고 표 내부에 불필요한 세로 스크롤바가 없으며, 최소 창 높이에서는 전체 페이지를 스크롤해 400 px 그래프에 접근할 수 있다.

권장 회귀 허용오차는 동일 환경/의존성에서 scalar `1e-8` 상대오차, 배열 `1e-7` 상대오차입니다. 외부 RocketCEA 또는 수치 라이브러리 버전을 바꾸면 기존 허용오차를 자동 승인하지 말고 원인을 검토합니다.

## 3. 열 해석 확인

근거 페이지는 `RPA_ThermalAnalysis.pdf` p. 7(Bartz), pp. 8-11(Film), pp. 11-18(Radiation/Regen), p. 19(TBC), pp. 21-22(결과 정의)입니다.

- [ ] Low/Medium/High 결과의 `section_count`가 각각 120/300/700이며 모든 x, radius, `Twg`, `Twi`, `Twc`, `Tc`, heat-flux 배열 길이와 일치한다.
- [ ] Regen과 Radiation 범위가 겹치면 분석이 차단되고 해당 세그먼트 이름이 경고에 나온다.
- [ ] 서로 다른 Regen 범위가 겹치면 분석이 차단되며, 경계점만 맞닿은 독립 회로는 각각의 입·출구 온도로 계산된다.
- [ ] Regen/Radiation의 Start·End 위치 선택에 따라 직접 mm 입력란이 올바르게 활성화/비활성화되고 `Conv Boundary`가 실제 실린더/수축부 경계로 해석된다.
- [ ] Regen coolant source를 엔진 산화제/연료로 바꾸면 coolant와 상대 질량유량이 혼합비에서 자동 산정되고 압력·온도만 편집 가능하다.
- [ ] Film temperature source를 Regen으로 바꾸면 연결 체인의 유효 coolant가 Film에 표시되고 잠기며, 수동 온도로 돌아가면 이전 Film coolant가 복원된다.
- [ ] Film `Injector Face`는 UI와 CFG에서 별도 모드로 유지되고 계산에서는 contour 시작점인 정확한 0 mm로 해석된다.
- [ ] Regen 대화상자의 Name/Start/End와 Film 대화상자의 Name/Injection position/Specified location이 최소 지원 폭에서 한 줄에 유지되며 텍스트가 잘리지 않는다.
- [ ] Regen roughness/TBC의 세부 입력은 Enable일 때만 나타나고, Surface roughness 카드가 대화상자 맨 아래에 위치한다.
- [ ] 삭제된 Regen을 coolant/temperature source로 참조하는 세그먼트가 inactive/broken으로 표시되고 분석이 차단된다.
- [ ] TBC가 없으면 `Twi == Twg`이고, TBC 사용 시 모든 온도·열유속이 유한하며 에너지 수지 residual이 설정 허용치 안이다.
- [ ] counter-flow와 co-flow Regen에서 coolant 진행 방향과 입출구 온도 표기가 일치한다.
- [ ] Thermal Analysis 상단 표에 Regen별 coolant 입·출구/상승 온도와 최대 고온가스측 내벽 온도가 표시된다.
- [ ] Regen 요약표의 냉각제/추진제 종류, 입구·출구 압력과 차압이 각 독립 회로별로 표시되고 연결 회로는 원본 냉각제 및 앞 세그먼트 출구 압력을 이어받는다.
- [ ] Channel occupied angle을 사용하는 Regen은 요약표에 대표 channel/rib 폭이 유한한 mm 값으로 표시된다.
- [ ] 그래프 아래 축방향 표는 양 끝점을 포함한 약 30개 대표 station만 표시하고, x·heat flux·`Twg`·`Twi`·`Twc`·`Tc`·`pc`·`wc`·`rho`가 원본 해석 배열과 일치한다.
- [ ] Thermal Analysis의 온도 y축은 정확히 0 K에서 시작하며, contour는 온도 곡선과 픽셀 단위로 동일한 x축을 사용하고 중심선 위 상반부의 x/y가 같은 축척이다.
- [ ] Thrust Chamber Size 하단에 Rao 형상 참고 이미지가 표시되고 Film BLC 체크의 초기 상태는 해제다.
- [ ] Thrust Chamber Size의 Performance와 Mass Flow Rates가 같은 행에 배치되고 residence time·chamber pressure·exit pressure가 Performance에 표시되며 모든 metric 크기가 일관된다.
- [ ] Chamber & Rao geometry가 `Rc/Rt/Re`, `Lcyl/Lc/Le`, `R1/R2/Rn`, `b/Tn/Te`, `Ac/At/Ae/At/L*`의 3열 × 5행으로 표시되며, 입력 및 직접 길이 모드의 L*가 모두 `(원통부 체적 + 수축부 체적) / At`와 일치한다.
- [ ] Rao 자동 각도는 NASA 도표 안에서 기존 보간과 `Ae/At=14`, `80%`의 Tn 27.4°, Te 9.8°를 유지하고, 밖에서는 RPA 실측 대조 유동식을 사용한다. 확장비 2/4/100/250/1000 및 길이 50/80/120%의 자동 입력이 계산되며, 비유한/잘못된 입력과 한 각도만 지정한 입력은 오류로 표시된다.
- [ ] Tn/Te 직접 입력이 저장·복원되며, 이전 프로젝트의 빈 각도 입력은 자동 모드로 열린다. Bell metadata에 `nasa_sp125_chart_interpolation`, `rpa_observed_flow_auto` 또는 `user_specified`와 출처·유동 상태·자동 보정 여부가 기록된다.
- [ ] Rao 원호–포물선의 실제 접선이 지정한 Tn/Te와 일치하며, 출구 면적비·노즐 길이·점 수가 요청값과 일치한다. 유효하지 않은 원호 또는 접선교점을 강제 보정하여 형상을 생성하지 않는다.
- [ ] Medium과 High의 peak `Twg` 및 총 열부하 차이를 기록하여 격자 수렴성을 확인한다. 유의미한 차이가 남으면 High만으로 상세 설계 결론을 내리지 않는다.
- [ ] 재료 표 범위 밖 온도에서 conductivity가 끝값으로 clamp된다는 정책을 결과 검토자가 알고 있다.
- [ ] CuCrZr(`10.1016/j.matchar.2024.114103`)와 AlSi10Mg(`10.3390/ma16144920`, Fig. 2f)는 LPBF 조건별 screening curve임을 기록하고, 실제 build 방향·열처리·lot data 없이 설계 허용치로 사용하지 않는다.
- [ ] IN625/IN718(Special Metals SMC-063/045), Ti64(NASA-TM-101660), C103(ASM Alloy Digest Cb-25)의 표 출처와 적용 온도 범위를 release 입력 자료와 함께 보존한다.

## 4. One-file EXE 검증

```powershell
PowerShell -ExecutionPolicy Bypass -File .\build_exe.ps1
Get-FileHash .\dist\LPA.exe -Algorithm SHA256
```

- [x] `dist`에 실행에 필요한 산출물이 `LPA.exe` 한 파일뿐이다.
- [ ] Python, MSYS2, 개발 도구가 없는 깨끗한 대상 PC/VM에서 EXE가 실행된다.
- [ ] `lpa/resources/logo.ico`가 Windows Explorer/작업 표시줄과 자식 대화상자에 표시되며, 앱 내부 navigation에는 별도의 이미지 로고가 표시되지 않는다.
- [ ] 네트워크 차단 상태에서 LOX/RP-1 분석을 실행하고 status가 `RocketCEA + Bartz`이며 이상기체 fallback warning이 없다.
- [x] 첫 RocketCEA 실행 시 사용자 홈의 `RocketCEA` 폴더에 `f.inp`, 초기 `f.out`, `temp.dat`, `thermo.lib`, `trans.lib`를 만들 수 있다.
- [ ] 사용자 홈에 쓰기 권한이 없는 계정에서 RocketCEA 실패 메시지가 명확하다.
- [x] 공백 및 한글이 포함된 일반 사용자 프로필에서도 `C:\UserData`나 관리자 권한 없이 실제 `%USERPROFILE%\RocketCEA`에 CEA 작업 파일이 생성된다.
- [ ] 프로젝트 Save/Open round-trip 후 입력과 Cooling segment의 순서·연결 ID가 보존된다.
- [ ] 결과 CSV export가 Unicode 경로와 공백이 포함된 경로에서 성공한다.
- [x] EXE를 다른 디렉터리에서 실행해도 로고와 RocketCEA data를 찾는다.
- [ ] Windows Defender 및 조직 표준 보안 스캐너를 통과하고, 배포본에 코드 서명 후 SHA-256을 release 기록에 보존한다.

## 5. 알려진 모델 한계 승인

- [ ] Release note에 정상상태 1-D/준 1-D 모델, 경험식 기반 Film/BLC와 coolant 물성, RocketCEA 실패 시 ideal-gas fallback 가능성을 명시한다.
- [ ] 비정상, CFD/FEA, 연소 불안정, two-phase/boiling 위기, 구조·피로·수명·제작 공차 및 안전 인증은 범위 밖임을 명시한다.
- [ ] RocketCEA 및 동봉 의존성의 라이선스/고지/소스 제공 의무를 배포 담당자가 검토한다.

## 검증 기록 (0.10.0, 이전 릴리스)

| 항목 | 값 |
|---|---|
| LPA version / commit | 0.10.0 / local workspace |
| 검증 일시 / 담당자 | 2026-07-21 19:50 KST / Codex (116 tests + packaged smoke) |
| Windows version / architecture | Windows 11 10.0.22631 / AMD64 |
| Python / Tk version | Python 3.14.0 / Tk 8.6 |
| NumPy / SciPy / Matplotlib / RocketCEA | 2.4.2 / 1.17.0 / 3.10.8 / 1.2.3 |
| PyInstaller / hooks version | 6.21.0 / 2026.6 |
| `LPA.exe` 크기 / 서명 | 41,200,773 bytes (39.29 MiB) / NotSigned |
| `LPA.exe` SHA-256 | `303F701F079E25FF80BDF578C6887A9E6A2C613CBADC9821C81654EBDE4566F2` |
| 단일 EXE 격리 smoke | PASS — one-file EXE의 GUI 응답 및 창 제목 `LPA 0.10.0` 확인 (build host) |
| 기준 project 파일 | 기본 LOX/RP-1 smoke project |
| Medium vs High peak `Twg` 차이 | |
| 미해결 warning / 승인자 | 미서명 배포본의 SmartScreen 가능성; 물리적 clean target PC/VM 최종 승인은 별도 수행 |

## 검증 기록 (0.11.0, 이전 릴리스)

| 항목 | 값 |
|---|---|
| LPA version / commit | 0.11.0 / local workspace |
| 최종 검증 일시 / 담당자 | 2026-09-18 16:08 KST / Codex 및 독립 코드 검토 |
| Windows version / architecture | Windows 11 10.0.22631 / AMD64 |
| Python / Tk version | Python 3.14.0 / Tk 8.6 |
| NumPy / SciPy / Matplotlib / RocketCEA | 2.4.2 / 1.17.0 / 3.10.8 / 1.2.3 |
| PyInstaller / hooks version | 6.21.0 / 2026.6 |
| 전체 회귀시험 | `python -m pytest tests -q --basetemp tmp/pytest-final-0110-20260918`: **209 passed in 31.59s**, 실패·skip 없음 |
| 구문 / 패치 검사 | `compileall` (`main.py`, `lpa`, `tests`), `LPA.spec` compile, `git diff --check` PASS |
| 실제 RocketCEA 조합 | 산화제 4종 × 연료 10종 **40조합** 모두 유한한 결과, fallback 없음 |
| 입력·호환성·연결 | 질량분율 검증, 소수점 저장·재열기, 이전 농도별 CFG 이행, 농도별 CEA 캐시, Regen/Film 조성 전달 PASS |
| 자동 O/F | 최대 C* 목적함수와 출구조건 독립성 PASS; 기본 조성의 자동 O/F **1.23479916** |
| 기본 엔진 | LPA Demonstrator, 2000 N @ 1 atm, Pc 20 bar(a), Ac/At 6.25, L* 1.2 m, O/F 1.3 (수동), LOX / Ethanol 70 wt% PASS |
| 최종 EXE 빌드 | `build_exe.ps1 -SkipInstall` PASS; 빌드 로그 `tmp/build-0.11.0.log` |
| `LPA.exe` 크기 / 서명 | **41,261,895 bytes** / NotSigned |
| `LPA.exe` FileVersion / ProductVersion | 0.11.0 / 0.11.0 |
| `LPA.exe` SHA-256 | `69DABB955AF7F32F2389F1EAB0936923F6841B60D6669B07539F29AF43448820` |
| 패키징 시작·종료 | 창 제목 `LPA 0.11.0`, GUI 응답, 새 프로젝트의 불필요한 저장 확인 없이 정상 종료(exit 0) PASS |
| 패키징 UI·계산 | 기본 엔진 해면추력 **2.000 kN**, Pc **20.000 bar(a)**, Ac/At **6.250**, L* **1200.000 mm** 확인. 자동 C* O/F, H2O2/IPA 질량분율 표시, LNG 조성 표시 및 H2O2 90 wt% / LNG 계산을 직접 실행해 `rocketcea + Bartz` 완료 확인 |
| 독립 검토 | 조성·물성·CEA 상태·C* 최적화에서 중대한 오류나 회귀 없음. 매우 묽은 수용액의 CEA 실패 시 경고와 fallback 반환 확인 |
| 적용 범위 / 잔여 배포 검증 | 개발 PC에서 소스·실행 파일 검증 완료. 별도 clean PC/VM, 코드 서명 및 보안 스캐너 검증은 수행하지 않음. 냉각 물성과 LNG 엔탈피 근사 범위는 `PROPELLANT_AUDIT.md` 참조 |

저장소 루트의 제한 없는 pytest 수집은 기존 `tmp` 시험 디렉터리의 Windows 접근권한 오류로 중단되어, 정식 시험 디렉터리인 `tests`를 명시해 전체 시험을 완료했다. 위 기본 실행 명령도 같은 범위를 명시한다.

## 검증 기록 (0.12.0, 이전 릴리스)

| 항목 | 값 |
|---|---|
| LPA version / commit | 0.12.0 / local workspace |
| 최종 검증 일시 / 담당자 | 2026-10-08 08:39:04 KST / Codex 및 독립 패키지 검토 |
| 반영 범위 | NASA SP-125 Rao 각도 보간, 직접 Tn/Te 입력과 저장, 접선 보존 및 정확한 출구·점 수, 기존 GUI 규칙에 따른 정적 안내문 제거 |
| Python / Tk version | Python 3.14.0 / Tk 8.6 |
| NumPy / SciPy / Matplotlib / RocketCEA | 2.4.2 / 1.17.0 / 3.10.8 / 1.2.3 |
| PyInstaller / hooks version | 6.21.0 / 2026.6 |
| 전체 회귀시험 | **299 passed in 20.33s**, 실패·skip 없음; `tmp/test-0.12.0.log` |
| 구문 / 패치 검사 | `compileall` (`main.py`, `lpa`, `tests`), `LPA.spec` compile, `git diff --check` PASS |
| 버전 일치 | Python·README·CHANGELOG·CFG·창 제목·Windows 고정/문자열 리소스 모두 **0.12.0**; 전용 버전 일치 회귀시험 3개 추가 |
| 최종 EXE 빌드 | `build_exe.ps1 -SkipInstall` PASS; `tmp/build-0.12.0.log`에 빌드와 현재 preflight의 LPA 버전·환경 기록 |
| `LPA.exe` 크기 / 서명 | **41,267,963 bytes** / NotSigned |
| `LPA.exe` FileVersion / ProductVersion | **0.12.0 / 0.12.0**, 고정 리소스 `(0, 12, 0, 0)` |
| `LPA.exe` SHA-256 | `A74D3129573AA32E3773BD6DBED3A00E026998202F214FB655A1026E6D1EBEBF` |
| 버전별 ZIP | `dist/LPA v0.12.0.zip`, **40,808,031 bytes**, `LPA.exe` 단일 파일; ZIP 내용과 최종 EXE 바이트 일치 |
| ZIP SHA-256 | `7D00C02D6D14519054B41D0C18AEE80C17AB4C7A21FB0E4284C84388C0DB784D` |
| 내장 코드·리소스 | 변경 모듈 8개 및 `main.py`가 현재 소스의 최적화 bytecode와 일치; 아이콘·Rao 참고 이미지 SHA-256 일치 |
| 내장 Rao 기준값 | `rao_angles(14, 0.8) = (27.4, 9.8)`; 범위 밖·비유한 입력 6건의 명시적 오류 PASS |
| 패키징 시작·종료 | 창 제목 **LPA 0.12.0**, GUI 응답, 정상 닫기와 exit **0** PASS; `tmp/smoke-0.12.0.log`, `tmp/release-0.12.0-smoke.json` |
| 프로젝트 호환 | 자동 빈값·이전 프로젝트·직접 Tn/Te 저장/복원과 core 직렬화 PASS; 프로젝트 schema `lpa-project/1` 유지 |
| 적용 범위 / 잔여 배포 검증 | 개발 PC에서 소스·실행 파일 검증 완료. 별도 clean PC/VM, 코드 서명 및 보안 스캐너 검증은 수행하지 않음. 이전 검증 기록과 0.10.0/0.11.0 ZIP은 보존 |

버전 기록은 `CHANGELOG.md`에 KST로 남기고 빌드·시험·smoke 로그를 위 경로에 보존했다. 기존 프로젝트에는 별도 런타임 파일 logger가 없으며, 이번 로깅 반영은 기존 변경 이력·빌드·검증 기록 범위이다. Rao 각도 표의 판독 근사와 기하 검증 범위는 [Rao 검증 문서](RAO_CONTOUR.md)를 참조한다.

## 검증 기록 (0.13.0, 이전 릴리스)

| 항목 | 값 |
|---|---|
| LPA version / commit | 0.13.0 / local workspace |
| 검증 일시 / 담당자 | 2026-10-08 09:21:34 KST / Codex 및 독립 수치·통합·패키지 검토 |
| 자동 각도 확장 | NASA 도표 밖에서 실제 RPA Script 출력으로 대조한 유동 관계식을 자동 사용; 입력 길이와 Rn/Rt 유지, 필요한 각도 조정과 경고 기록 |
| RPA 측정 근거 | 실제 입력·Me·목/출구 K·Tn/Te **20개 사례**, 실행 파일 버전·해시를 `tests/fixtures/rpa_rao_4_0_13.json`에 보존. 내장 순수 유동식 최대 오차 **2.84e-14 degrees** |
| 전체 회귀시험 | **390 passed in 19.58s**, 실패·skip 없음; `tmp/test-0.13.0.log` |
| 실제 성능·형상 통합 | RocketCEA+Bartz, 확장비 **2/4/100/250/1000 × 길이 50/80/120% 15조합** PASS. 접선·면적비·길이·300점·유동 출처·JSON·경고 전달 확인; `tmp/rao_extended_integration_20261008.json` |
| 열 해석·직접 입력 | 확장비 100 Regen Low 120점, 벽온도 유한·13회 반복 수렴. 직접 Tn45/Te10 유지; `tmp/rao_extended_thermal_manual_20261008.json` |
| 기하 제약 독립 검증 | 임의 5,000조합에서 유효 4,503 / 예상 오류 497, 판정 불일치 0. 지정 치수로 불가능한 확장비 1.1/80%는 명확한 기하 오류 |
| 버전 일치 | Python·README·CHANGELOG·CFG·창 제목·Windows 고정/문자열 리소스 모두 **0.13.0** |
| 구문 / 패치 검사 | `compileall` 및 `git diff --check` PASS |
| 최종 EXE 빌드 | `build_exe.ps1 -SkipInstall` PASS; `tmp/build-0.13.0.log` |
| `LPA.exe` 크기 / 서명 | **41,276,779 bytes** / NotSigned |
| `LPA.exe` FileVersion / ProductVersion | **0.13.0 / 0.13.0**, 고정 리소스 `(0, 13, 0, 0)` |
| `LPA.exe` SHA-256 | `11D90AD49AC3D1ECFCCEE73A6906C73B62C0CF7CDB69DC338799CB42904BCA95` |
| 버전별 ZIP | `dist/LPA v0.13.0.zip`, **40,816,497 bytes**, 동일한 `LPA.exe` 단일 파일 |
| ZIP SHA-256 | `B241A51FEA52CCE614093D0B8349A4683667C18A3B9ECC98476DAC049DC06CAD` |
| 내장 코드·리소스 | 모듈 14개 및 `main.py` bytecode 일치, 리소스 일치, 외부 RPA EXE/DLL 의존성 없음 |
| 내장 형상 실행 | 내장 모듈만으로 확장비 **1.0001/2/4/100/250/1000**, 80%·120점의 정확한 출구·길이·접선 확인. NASA14/80%의 27.4/9.8 유지 |
| 패키징 시작·종료 | 창 제목 **LPA 0.13.0**, 응답·정상 닫기·exit **0** PASS; `tmp/smoke-0.13.0.log`, `tmp/release-0.13.0-smoke.json` |
| 적용 범위 / 잔여 배포 검증 | 개발 PC에서 검증 완료. 별도 clean PC/VM, 서명·보안 스캐너 검증은 수행하지 않음. 기존 0.12.0 및 이전 ZIP·기록 보존 |

RPA 유동 관계식은 같은 Me/K로 평가했을 때의 실측 일치이며, 전체 RPA 해석과 열역학·길이·최적화 결과까지 동일하다는 뜻은 아니다. NASA 도표와 유동식의 선택 경계에서 각도가 불연속적으로 바뀔 수 있다는 정책과 자동 기하 보정 방식은 [Rao 검증 문서](RAO_CONTOUR.md)에 기록했다.

## 검증 기록 (0.14.0)

| 항목 | 값 |
|---|---|
| LPA version / commit | **0.14.0** / 기존 미커밋 변경을 보존한 local workspace; commit/push 없음 |
| 검증 일시 | **2026-10-11 18:50 KST** |
| 반영 범위 | 기존 검토의 P1 5건 / P2 23건 / P3 6건, 총 34건. [항목별 수정·신뢰도 평가](RELEASE_REMEDIATION_2026-10-11.md) 및 열전달 추가 검증 참조 |
| 환경 | CPython **3.14.0**, Tk **8.6**, NumPy **2.4.2**, SciPy **1.17.0**, Matplotlib **3.10.8**, RocketCEA **1.2.3**, CoolProp **8.0.0** |
| 전체 회귀시험 | **525 passed in 45.64s**, failure/error/skip 없음. `tmp/test-0.14.0.log`; 모든 GUI/PNG assertion 유지 |
| 시험 환경 결함 | 기본 FD capture의 Tcl 파일채널 오류를 A/B 재현하고 sys capture로 수정. 제품의 예외 은폐·자산 fallback·test skip을 추가하지 않음 |
| 독립 계산 검증 | NASA 운동량/압력추력·기체 초크 식, CEA getter/station transport, HEOS 상태·혼합물 h 변화, 연속방정식, 기하 미분/면적–Mach, fin/원통 저항, 셀 교집합·에너지 보존 |
| CEA 동시성 | 프로세스 내 RLock, 실행별 `%USERPROFILE%\RocketCEA\lpa-run-<PID>-<ID>` 작업 폴더. 한글/공백 프로필 및 같은 프로필 두 프로세스 병렬 회귀 PASS. native prefix 길이를 위한 ASCII 128/129자 경계 검증 |
| 실제 공급 피드백 | CEA+CoolProp, Et70 부분 5 mm Regen: **8회** 수렴. 최종 ΔT **0.00919 K**, Δp **0.000486 bar**. 120 station 중 3개 벽온도만 계산하므로 전체 엔진 정확도 검증이 아님; screening 및 미해석 경고 유지. `docs/thermal_audit_outputs_0140/partial_feed_feedback.json` |
| 실제 Bartz audit | 최대 독립 식 상대 차이 **8.522×10⁻⁷**. 기존 GOX/GCH4 water 사례는 **97/300 station** 후 2상 중단·unsupported. 단상 부분 엔탈피 잔차 **5.82×10⁻¹¹ W** |
| 추가 thermal matrix | 8 coolant / 9 pressure-state / 3 gray-radiation 민감도 + 350/700/1400 × epsilon 0/.02/.08/.16. 원본 JSON/CSV 및 재생성 도구 보존 |
| UI 레이아웃 | Tk scaling **1.333/1.667/2.0**, 창 **1080×700/1460×900**, 8페이지 clipping 대조. 실제 OS DPI 전환과는 구분 |
| 구문 / 패치 검사 | 전체 runtime·test·tool Python 및 spec compile, `git diff --check` PASS |
| EXE 빌드 | `build_exe.ps1 -SkipInstall` PASS; `tmp/build-0.14.0.log`. HEOS와 CEA preflight 포함 |
| 내장 코드·리소스 | **33개 LPA 모듈 및 main.py**가 현재 소스 optimize=1 bytecode와 일치. icon/Rao PNG exact-byte match. CoolProp/CEA/SciPy native 라이브러리와 각각의 라이선스 고지 포함. `tmp/release-0.14.0-archive.json` |
| 번들 EOS·계산 | EXE에서 추출한 모듈/native 파일만 `CPython -I -S`에서 로딩: LOX 150 K/20 bar rho **61.40243 kg/m³**, gas; CH4 200 K/50 bar Cp **7272.58668 J/(kg·K)**, supercritical, Cp peak **193.28393 K**. CEA vacuum Isp **288.66530 s**, 단상 물 Regen 엔탈피 잔차 **5.78×10⁻⁵ W**. `tmp/release-0.14.0-native.json` |
| 번들 시험 한계 | 위 추출 검증은 site-packages 의존성을 배제했지만 호스트 CPython 3.14 인터프리터를 사용했다. 실제 배포 EXE의 clean-machine 전체 계산시험을 대체하지 않음 |
| 패키징 시작·종료 | PATH에서 Python/개발 도구 제거, PYTHONPATH/PYTHONHOME 비움. 실제 EXE 창 제목 **LPA 0.14.0**, 응답·정상 닫기·exit **0** PASS. `tmp/smoke-0.14.0.log`, `tmp/release-0.14.0-smoke.json` |
| EXE 크기 / 서명 | **80,418,763 bytes** / **NotSigned** |
| FileVersion / ProductVersion | **0.14.0 / 0.14.0** |
| EXE SHA-256 | `39B910B75A6A1DDE413F73BA3C5B63A8281054041E5622CCBF14A782AFF4AA33` |
| 버전 ZIP | `dist/LPA v0.14.0.zip`, **79,719,089 bytes**, 동일 `LPA.exe` 단일 파일; 이전 ZIP 보존 |
| ZIP SHA-256 | `80C45557F206A5A09D4CC1E25442F0E063E41702E2B94E3B2B8EFCC0D88D411A` |
| 잔여 외부 검증 | clean PC/VM 전체 계산, 실제 OS DPI 변경, 코드 서명·보안 스캐너, 재배포 소스 제공 방식은 미검증. 연소/열시험·CFD/FEA·구조/수명 검증은 수행하지 않음 |

물리 적용범위는 수치 수렴과 별도다. 2상/CHF/dryout/검증된 초임계 HTD, 액체 Film 증발/coverage, 분광 복사/soot, 반응성 냉각제 분해·coking, 매니폴드/국소/가속 손실, closeout의 2D 전도, transient/ablative/수명 모델은 지원하지 않는다. 단상 EOS와 보정된 정상상태 1D 결과도 실제 장치별 실측 보정이 필요하다.

## 검증 기록 (0.15.0)

기록일: **2026-10-11 KST**. 0.14.0의 검토 수정 사항을 보존하고 자동 O/F를 Maximum theoretical vacuum Isp로 변경했다. 아래는 이번 릴리스의 실제 실행 결과다.

| 항목 | 결과 |
|---|---|
| 버전·작업 상태 | **0.15.0**, 기존 미커밋 변경 보존, commit/push 없음 |
| 전체 회귀시험 | **564 passed in 65.78s**, failure/error/skip 없음. `tmp/test-0.15.0.log`; GUI/PNG assertion 유지 |
| 자동 O/F 독립 검증 | 저장된 CEA 10조건 최대점, 독립 SciPy 탐색, O/F 주변 비교, 고정 Pe candidate별 Ae/At, shifting/throat-frozen, 조성·공급 T/P, 손실·Film 독립성 및 FAC chamber-frozen 거절 PASS |
| 대표 새 자동값 | LOX/Et70 Pc20/AcAt6.25: AeAt5 **1.31342082 / 278.71864135 s**, AeAt40 **1.42220763 / 327.53234783 s**; throat-frozen AeAt40 **1.24797405 / 312.13814649 s**. 이론 진공값이며 delivered 손실 제외 |
| backend 통합 | 분석 시 재최적화, 비활성 stored MR 무효값 무시, 원본 snapshot 보존. selected MR의 core thermal/solver coolant fraction 및 산화제·연료 질량 유량 일치 PASS |
| 실제 공급 피드백 | CEA+CoolProp 부분 5 mm Regen, auto ON, **8회 수렴**. O/F **1.33694073→1.33498074**, 최종 공급 **313.92303 K / 249.24823 bar**, outlet **313.93270 K / 249.24776 bar**. screening 및 미해석 구간 경고 유지. `docs/of_objective_review_20261011/auto_feed_feedback_0150.json` |
| UI | 새 목적 문구·관련 입력 trace/cache·결과 metadata, 1080×700/Tk scaling 1.333/1.667/2.0에서 새 checkbox req150/193/216px < 배정339/306/285px PASS. 실제 OS DPI 변경 시험과 구분 |
| 빌드 | `build_exe.ps1 -SkipInstall` PASS. `tmp/build-0.15.0.log`. HEOS/CEA preflight 포함 |
| 내장 코드·리소스 | **33개 LPA 모듈 및 main.py**가 현재 소스 optimize=1 bytecode와 일치. icon/Rao PNG exact-byte match, CoolProp/CEA/SciPy native 및 license 고지 포함. `tmp/release-0.15.0-archive.json` |
| 추출 번들 계산 | site-packages 없이 EXE 모듈/native만 isolated `CPython -I -S`에서 실행. auto objective/source **maximum theoretical vacuum specific impulse / rocketcea**, O/F **1.31342081877**, Isp **278.718641352 s**. CEA 성능·EOS·단상 물 Regen 수지 PASS. `tmp/release-0.15.0-native.json` |
| 실제 EXE 시작·종료 | Python/개발 도구를 PATH에서 제거, PYTHONPATH/PYTHONHOME 비움. 창 **LPA 0.15.0**, 응답 및 정상 닫기 exit **0** PASS. `tmp/smoke-0.15.0.log`, `tmp/release-0.15.0-smoke.json` |
| EXE 크기·서명·버전 | **80,421,612 bytes**, **NotSigned**, FileVersion/ProductVersion **0.15.0 / 0.15.0** |
| EXE SHA-256 | `54C6651E75B534AC5E1A66D134C1945A07E2959BF6A4FD4D64A54A8432BAA2F5` |
| ZIP | `dist/LPA v0.15.0.zip`, **79,721,909 bytes**, 동일 `LPA.exe` 단일 파일. 이전 ZIP 보존 |
| ZIP SHA-256 | `595E7CB7B793242CA6BB970263DCEF1BC11B84D76E62614344B4171DCEB082E9` |
| 적용 범위·한계 | RPA와 최적화 목적/출구조건 의미를 맞춤; 데이터베이스·비공개 수치 설정의 완전 일치 아님. fallback은 미검증 ideal-gas screening. 추출 번들 검증은 호스트 interpreter를 사용했으며 clean VM의 frozen EXE 전체 계산을 대체하지 않음. 0.14.0의 물리 미지원·외부 검증 범위 유지 |

항목별 변경 내용과 자체 신뢰도 평가는 [자동 O/F 검토 및 후속 적용](OF_OPTIMIZATION_REVIEW_2026-10-11.md)에 기록했다. 기존 검증 표의 C* 목적함수/0.14.0 EXE 기록은 해당 릴리스의 이력이며 위 0.15.0 기록으로 대체 적용한다.

## 검증 기록 (0.16.0b1 Beta)

기록일: **2026-10-19 KST**. 이전 미커밋 기능·문서·시험을 보존하여 통합한 Beta 배포다. 상세 변경·실행 기록은 [THERMAL_BETA_2026-10-19.md](THERMAL_BETA_2026-10-19.md), 원본 산출물은 [thermal_beta_outputs_0160](thermal_beta_outputs_0160/)에 보존한다.

| 항목 | 실제 결과 |
|---|---|
| 버전 | **0.16.0b1 Beta**, Windows fixed version **0.16.0.1**, prerelease flag **0x2** |
| 전체 회귀시험 | **598 passed in 72.01 s**. 최종 실패/skip 없음. `test_run.txt` |
| 가스측 | 별도 CEA frozen chamber Cp/Pr/mu/gamma, 실제 상류 R1 곡률. 실제 RPA fixed-wall 3지점 h/q 차이 3% 이내; 목 h -1.77%, q -1.88% |
| LNG | 150 K·20/25/30 bar 모두 액체 및 PH 가열·감압 정상. 25 bar rho **384.368775 kg/m³**. property-specific 12회귀 통과 |
| 2상 채널 | 순수유체 Li-Wu/Chen-Bennett, LM 마찰·HEM 가속/운동에너지 결합. 진단 원통 120/120 station, 16 station 2상, 에너지 잔차 **2.18e-11 W**. subcooled-boiling 선행영역 때문에 사례 전체 적용성 **unsupported** 유지 |
| 표시·중단 | 2상 음영, 질량건도·regime CSV, 계산 완료 수 표시. 건도 제한·혼합물·결측 transport 중단과 중단된 상류/압력소진 회로의 하류 재개 차단 회귀 통과 |
| 원본 기록 | `summary.json`, `two_phase_stations.csv`, `two_phase_channel.png`, test/build 원본 출력, property/RPA fixture·재현 스크립트 보존 |
| 빌드 | `build_exe.ps1 -SkipInstall` 성공. CPython 3.14.0, PyInstaller 6.21.0, CoolProp 8.0.0, ht 1.2.0, fluids 1.3.1. `build_run.txt` |
| 내장 소스 | **35개 LPA 모듈 및 main.py** optimize=1 bytecode 일치. icon/Rao PNG 일치, dependency license/metadata 포함. `archive_check.json` |
| 추출 번들 계산 | host site-packages 없이 isolated **-I -S** CPython에서 추출한 EXE 코드/native 실행. 실제 CEA 성능·자동 O/F·frozen reference, LNG150K25bar, 단상/2상 에너지 수지 통과. `native_runtime_check.json`. 호스트 interpreter 사용이므로 clean-VM 검증과 구분 |
| 실제 EXE | 창 제목 **LPA 0.16.0b1 Beta**, 응답·정상 닫기·exit **0** 확인. `exe_smoke.json` |
| EXE | **81,826,612 bytes**, FileVersion/ProductVersion **0.16.0b1**, 코드 서명 없음 |
| EXE SHA-256 | `c97aeebca800873fd1ba6792a78452a0f67ca3bd72bd8509bc01298185c606a4` |
| Beta ZIP | `LPA-0.16.0b1-Windows-x64-Beta.zip`, **81,212,520 bytes**. EXE, README, third-party notices/licenses 포함 |
| ZIP SHA-256 | `cd4dbfe7304349adfd246201961b519c20bc363f923948fcba1c60aebd06fea9` |
| RocketCEA 소스 | 수정하지 않은 **1.2.3** PyPI sdist, **69,126,862 bytes**. PyPI SHA-256 일치 `66f306407f11ba36186342dc2716417d3a5c9d94c95b0c5663380091bb11caa9` |
| GitHub 게시 확인 | 기존 비공개 **giju0508/LPA** main 업로드, **v0.16.0b1** prerelease 게시 완료. release ID **416589174**, release code commit **29dc05aa5e8e3587e8b51d3753d7f137cad7f797**. ZIP·RocketCEA 소스·SHA256SUMS의 GitHub server digest 일치, 3개 asset uploaded. `github_publication.json`; 공개 범위 변경 없음 |

수치 수렴·에너지 수지·RPA 대조는 실제 엔진 검증을 대체하지 않는다. x=0.7은 dryout 예측이 아닌 계산 제한이다. 혼합물 비등 열전달, CHF/dryout/post-dryout, 검증된 초임계 HTD, subcooled boiling, 유동 불안정·choking, 매니폴드/국소 손실 및 구조·수명은 여전히 미지원 또는 미검증이다. REFPROP는 별도 설치·사용권이 필요하며 배포본에 포함하지 않았다. RP-1의 완전한 NIST surrogate는 필요한 성분/FLD 부재로 적용하지 않았다. clean PC/VM 전체 계산·실제 OS DPI 전환·코드 서명·연소/열시험은 수행하지 않았다.

## 검증 기록 (0.16.0b2 Beta)

기록일: **2026-10-19 KST**. 시작 import 도중의 `KeyboardInterrupt` 처리와 소스 실행환경 안내를 보강했다. 아래 값은 [startup_beta_outputs_0160b2](startup_beta_outputs_0160b2/)의 JSON·시험·빌드 원본을 대조하여 기록했다. 0.16.0b1 및 이전 검증 결과는 해당 버전의 이력으로 보존한다.

| 항목 | 실제 결과 |
|---|---|
| 버전 | **0.16.0b2 Beta**. Python·README·CHANGELOG·Windows 버전 정합 회귀 포함 |
| 시작 중단 처리 | launcher의 시작 import/GUI 생성 중 `KeyboardInterrupt`를 기록하고 **exit 130** 반환. 실제 subprocess에서 traceback·표준출력·표준오류 없이 종료하는 회귀, 정상 실행 및 실제 `ModuleNotFoundError` 전달 회귀 포함. 기존 GUI mainloop의 정상 종료 처리는 유지 |
| 소스 Python | **`C:\Python314\python.exe`, CPython 3.14.0**. user-site의 NumPy 2.4.2, SciPy 1.17.0, Matplotlib 3.10.8, RocketCEA 1.2.3, CoolProp 8.0.0과 고정 버전 의존성 확인. `runtime_import_check.json` |
| 누락 의존성 조치 | 위 소스 Python에 **ht 1.2.0 / fluids 1.3.1**을 `requirements.txt`로 설치. `pip check`: **No broken requirements found.** `dependency_install.txt`, `runtime_import_check.json` |
| import 확인 | 기록된 실행에서 TkAgg import **0.21848 s**, app import **0.30527 s**. 원래의 패키지/import 실패는 재현되지 않음. 이는 해당 import 측정이며 전체 최초 시작시간이나 원래 중단 신호의 발생 원인을 확정하는 시험은 아님 |
| 전체 회귀시험 | **603 passed in 77.10 s**, failure/error/skip 없음. `test_run.txt` |
| 실제 소스 GUI | 글로벌 Python으로 `-u main.py` 실행. 창 **LPA 0.16.0b2 Beta**, 응답 **true**, 정상 닫기 **true**, exit **0**. stdout/stderr 모두 **0 bytes**. `source_smoke.json`, `source_stdout.txt`, `source_stderr.txt` |
| 빌드 | `build_exe.ps1 -SkipInstall` 성공. PyInstaller 최종 완료 시각 기준 **85.36 s**. CPython 3.14.0/Tk 8.6 및 수치 라이브러리·CoolProp/CEA preflight 포함. `build_run.txt` |
| 내장 코드·리소스 | **35개 LPA 모듈 및 main.py**가 현재 소스의 optimize=1 bytecode와 일치. icon/Rao PNG 일치. CoolProp·RocketCEA·SciPy·ht·fluids의 라이선스 포함 확인. `archive_check.json` |
| 실제 frozen GUI | `dist/LPA.exe` 실행. 창 **LPA 0.16.0b2 Beta**, 응답 **true**, 정상 닫기 **true**, 부모 프로세스 exit **0**. Windows PowerShell 5.1의 종료 코드 확인을 위해 Process.Handle 유지. `exe_smoke.json` |
| Windows 버전·서명 | FileVersion/ProductVersion **0.16.0b2 / 0.16.0b2**, 고정 버전 **0.16.0.2**, prerelease flag **0x2** / `IsPreRelease=true`. 코드 서명 없음 |
| 추출 번들 실행 | host site-packages 없이 **isolated -I -S CPython 3.14**에서 EXE 추출 코드/native 실행. CoolProp/NumPy가 `tmp/release-0.16.0b2-bundle`에서 로드됨. `native_runtime_check.json`. 호스트 interpreter를 사용하므로 clean-machine frozen EXE 전체 계산 검증과 구분 |
| 추출 번들 물성·CEA | LOX 150 K/20 bar gas rho **61.402430 kg/m³**; CH4 200 K/50 bar supercritical Cp **7272.58668 J/(kg·K)**, Cp peak **193.28393 K**; LNG 150 K/25 bar rho **384.368775 kg/m³**. 실제 CEA vacuum Isp **288.665295 s** |
| 추출 번들 자동 O/F·열수지 | `rocketcea`, maximum theoretical vacuum specific impulse 목적의 O/F **1.31342081877**, 이론 진공 Isp **278.718641352 s**. 단상 열해석 수렴·적용성 **screening**, 수지 잔차 **7.28e-5 W**. 2상 **16 station** 사례의 운동에너지 포함 잔차 **2.18e-11 W**, 사례 전체 적용성은 **unsupported** 유지. `native_runtime_check.json` |
| EXE 크기 | **81,826,332 bytes**. `release_manifest.json` |
| EXE SHA-256 | `f9eb9b300cf2d09b88263d17e9d6dbc1a2d26dad9a598db5ac299be8a6f8ba98` |
| Beta ZIP | `LPA-0.16.0b2-Windows-x64-Beta.zip`, **81,212,876 bytes**. EXE·README·third-party notices/licenses 포함, ZIP 무결성 및 EXE/README 원본 일치. `release_manifest.json` |
| ZIP SHA-256 | `f9be161ddc6c61b3a50f3df09f961a26ed33aece510529c4eb4efb5e15c4d7ea` |
| GitHub 게시 확인 | 기존 비공개 **giju0508/LPA** main 및 **v0.16.0b2** tag 업로드, **Beta prerelease 게시 완료**. release ID **416639211**, release code commit **c766e63474d3eaff935995e8924e60a9db85ef8a**. ZIP·RocketCEA 대응 소스·SHA256SUMS **3개 asset uploaded**, 각 GitHub 서버 SHA-256 digest가 로컬 파일과 일치. 공개 범위 유지. `github_publication.json` |
| 미수행 검증 | **clean PC/VM**, 실제 **VS Code/Code Runner UI 자동조작**, 실제 OS DPI 전환, 코드 서명·보안 스캐너 및 연소/열시험은 수행하지 않음 |

`KeyboardInterrupt` traceback은 중단 신호를 받은 실행 위치를 나타낸다. Matplotlib import 위치에서 중단되었다는 사실과 글로벌 Python에서 두 의존성이 누락되었던 사실은 구분하며, 누락된 의존성을 원래 `KeyboardInterrupt`의 직접 원인으로 확정하지 않는다. 소스 GUI smoke는 명시한 Python의 실행·응답·정상 종료 검증이며 VS Code 확장의 실제 실행 설정이나 Stop 버튼을 자동 조작한 시험이 아니다. b1에 명시한 열전달 Beta의 물리 적용 한계는 그대로 유지한다.


## 검증 기록 (0.17.0b1 Beta)

2026-10-19 KST, Windows 11 x64 / CPython 3.14.0 / Tk 8.6에서 실행했다. 근거는 [버전별 원본 출력](thermal_review_outputs_0170/README.md)에 보존한다. 방법과 한계는 [열전달 검토](THERMAL_REVIEW_0170.md), [채널 상관식](CHANNEL_ENTRY_METHOD_2026-10-19.md), [물성 근거](property_review_0170.md)를 참조한다.

| 확인 | 실제 결과 |
|---|---|
| 버전 | Python/README/CHANGELOG/Windows 문자열 **0.17.0b1 Beta**, 고정 **0.17.0.1**, `IsPreRelease=true` |
| 전체 회귀 | **668 passed in 73.51 s**. 최종 원본 로그는 `test_run.txt`에 기록 |
| 실패 원인 교정 | 첫 전체 시험에서 GUI 2건이 실패했다. 새 DPI 시험이 Tk display scaling을 다음 시험에 남긴 문제로 확인하여 finally에서 원래 배율을 복원했다. 제품 assertions를 약화하지 않았다. 새 미계산 표시 시험의 예약 Matplotlib draw도 Tcl 종료 전에 처리한다 |
| 소스/환경 | compileall, `pip check` 통과. 기존 pinned runtime/build dependencies 유지 |
| 독립 문헌 대조 | NIST Table 10의 465개 k 데이터와 Table 12의 30개 μρ 데이터·단위를 원문과 전수 대조. low-P 점도식과 일치하지 않는 계측자료를 임의로 자동 연결하지 않음 |
| 채널 수식 | 입구식의 원문 shape 지수/길이척도/Fanning 대 Darcy를 확인. 12/120/700 셀 분할 적분, Re 2300/4000의 Nu/f 연속성·적용범위 회귀 포함 |
| 실제 입력 재검토 | 원본 CFG 미변경 SHA-256 확인. 1.3 mm: **49/300** 벽 해, 마지막 Tc **334.107562 K**, 부분 Δp **0.0453234 bar**. 1.8 mm 비교: **51/300**, 마지막 Tc **333.784448 K**. 둘 다 **unsupported**이며 실제 전체 채널 출구값으로 사용하지 않음 |
| 물성 행렬 | 실제 **21 PT + 8 포화상** 상태를 출처·상·수송/열역학 적용성과 함께 저장. N₂O/Ethanol 고온 transport 결측, native no-EOS 유체, RP-1 범위 이탈을 구분. LNG 150 K/25 bar는 액상 EOS 밀도 **384.368775 kg/m³**, 점도 결측으로 기본 열전달 미승인 |
| Windows 빌드 | PyInstaller **6.21.0**, hooks **2026.6** 단일 EXE 빌드 성공. `build_run.txt` |
| 소스/번들 일치 | EXE 추출 **36개 LPA 모듈 + main** 코드와 현재 소스 일치, native/resources 및 주요 dependency license 확인. `archive_check.json` |
| 실제 GUI 실행 | 글로벌 Python source 및 frozen EXE 모두 창 **LPA 0.17.0b1 Beta**, responding **true**, normal close **true**, exit **0**. source stdout/stderr 0 bytes |
| 추출 native 계산 | host site-packages 없는 `-I -S`에서 EXE 코드/native 라이브러리 실행. 실제 CEA/자동 O/F/LNG EOS/RP-1 450 K 거부/물 재생냉각·비등 통과. 실제 frozen EXE를 깨끗한 PC에서 전체 계산한 검증과는 구분 |
| 비등 수지 | 0.05 kg/s 물 원통 fixture에서 120개 벽 해, 35개 bulk 2상 지점. 열유입 **88625.197411 W**, 엔탈피 상승 **88620.129722 W**, 운동에너지 변화 **5.067690 W**, 잔차 **6.69e-11 W**. subcooled-boiling 가드 때문에 물리 상태는 **unsupported**로 유지 |
| ZIP | **53개** member의 원본 byte 일치와 ZIP 무결성 확인. EXE/최신 README/CHANGELOG/방법 근거 및 직접·간접 runtime 원본 license notices 포함. `release_manifest.json` |
| 공개 전 점검 | 기존 **5개 commit / 644 text blob occurrences**의 credential signature matches **0**. 비밀 전체 부재를 증명하는 검사는 아니며 실제 token 값은 출력하지 않음. 사용자 CFG/attachments/tmp/dist는 Git에 포함하지 않음 |
| 잔여 범위 | 실제 채널·하드웨어/clean-PC 전체 계산/코드 서명 미검증. 혼합물 2상 열전달, CHF/dryout, 검증된 고온 RP-1 EOS, 초임계 HTD·수명 미지원 |

파일 크기와 SHA-256:

| 파일 | bytes | SHA-256 |
|---|---:|---|
| LPA.exe | 81859474 | `ba9f9f873a628f630e3a30dcd51e1bcd94349940bff9047478da19bb1c55507f` |
| LPA-0.17.0b1-Windows-x64-Beta.zip | 81323798 | `9103a9ebef32438eeb47728b73bc56d05f9cd9fc1ebda5a04866c8de5649b68f` |
| rocketcea-1.2.3.tar.gz | 69126862 | `66f306407f11ba36186342dc2716417d3a5c9d94c95b0c5663380091bb11caa9` |


GitHub 최종 게시 확인: [giju0508/LPA](https://github.com/giju0508/LPA)를 **public**으로 전환하고 [v0.17.0b1 Beta](https://github.com/giju0508/LPA/releases/tag/v0.17.0b1)를 **published prerelease**로 게시했다. 게시 시각 **2026-10-19 04:52:19 KST**, release ID **416669826**, release code commit **b6caefbd58a8b54b69e589901a9522e656d37392**. ZIP·RocketCEA 대응 소스·SHA256SUMS **3개 asset**은 uploaded 상태이며 각 GitHub SHA-256 digest가 로컬 파일과 일치한다. 인증 없는 API에서 저장소/Release를 읽고 모든 asset의 다운로드 HEAD **HTTP 200 / 정확한 크기**를 확인했다. 현재 게시된 최신 Beta가 v0.17.0b1임을 별도로 확인했다. `github_publication.json`, `anonymous_publication_check.json`.

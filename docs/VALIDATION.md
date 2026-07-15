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
.\.venv-build\Scripts\python.exe -m pytest -q
.\.venv-build\Scripts\python.exe -c "compile(open('LPA.spec', encoding='utf-8').read(), 'LPA.spec', 'exec')"
```

- [ ] 모든 명령의 exit code가 0이다.
- [ ] `python main.py` 실행 후 창이 잘리지 않고 1080 x 700 최소 크기에서 각 입력 페이지를 끝까지 스크롤할 수 있다.
- [ ] DPI 100%, 125%, 150%에서 텍스트, combobox, 표 헤더와 Matplotlib toolbar가 겹치거나 잘리지 않는다.
- [ ] 메인 창 제목은 프로젝트 저장·수정 상태와 관계없이 `LPA 0.7.0`만 표시되고, 탭 제목·설명은 Save/Run 옆 상단 영역에 한 번만 표시된다.
- [ ] VS Code Code Runner Stop 또는 터미널 `Ctrl+C`로 중단해도 `KeyboardInterrupt` traceback 없이 executor와 Tk 창이 정리된다.
- [ ] 좌측 INPUT/RESULTS 항목의 숫자 접두어가 선택·비선택 상태 및 DPI 100~150%에서 깨지지 않는다.
- [ ] 자동 O/F를 선택하면 입력란이 잠기고 현재 추진제·압력·노즐 조건에 대한 최대 진공 비추력 O/F와 계산 출처가 표시되며, 해제하면 다시 직접 입력할 수 있다.

## 2. 기준 수치 확인

동일한 입력 JSON을 보존하고 버전별 결과를 비교합니다. 절대 오차뿐 아니라 계산 backend와 warning도 함께 기록합니다.

- [ ] RocketCEA LOX/RP-1 기준점에서 backend가 `rocketcea + Bartz`이고 c-star, chamber temperature, gamma, sea-level/optimum/vacuum thrust 및 Isp가 유한·양수이다.
- [ ] `RPA_LiquidRocketEngineAnalysis_II.pdf` pp. 20-22의 CEA2 비교 사례 중 재현 가능한 propellant/pressure/mixture-ratio 조합을 별도 fixture로 고정하고, RocketCEA/RPA 정의와 단위 차이를 기록한 허용오차 안에 든다.
- [ ] area-ratio 입력과 ambient-pressure 입력으로 계산한 nozzle exit 조건이 서로 일관되며, throat Mach가 약 1이고 축방향 압력은 유한하다.
- [ ] 직접 Dc와 직접 Dt 조합에서 `Ac/At = (Dc/Dt)²` 및 contour의 Dc가 입력과 일치하며, 명목 추력 기준에서도 반복 계산 후 동일 관계가 성립한다.
- [ ] 0.3.x 이하 프로젝트를 연 뒤 수축부 정의가 기존 Ac/At 방식으로 복원되고 저장·재열기 후 선택 방식과 값이 유지된다.
- [ ] Film 0%일 때 with/without-film 결과가 같고, Film 사용 시 질량 보존(`total = oxidizer + fuel + film`)이 허용오차 안에서 성립한다.
- [ ] throttle/ambient range의 행 수가 입력 points와 같고 양 끝값이 정확히 포함된다.

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
- [ ] Chamber & Rao geometry가 `Rc/Rt/Re`, `Lcyl/Lc/Le`, `R1/R2/Rn`, `b/Tn/Te`, `Ac/At/Ae/At/L*`의 3열 × 5행으로 표시되며 직접 길이 모드에서도 L*가 유한하다.
- [ ] Bell contour metadata에 `rao_angle_method=lpa_empirical_approximation_not_rpa`가 기록되고, RPA 4.0.13 자동 Tn/Te와 동일하다고 오인하지 않는다.
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

## 검증 기록

| 항목 | 값 |
|---|---|
| LPA version / commit | 0.7.0 / local workspace (Git metadata 없음) |
| 검증 일시 / 담당자 | 2026-07-14 07:29:14 KST / Codex |
| Windows version / architecture | Windows 11 10.0.22631 / AMD64 |
| Python / Tk version | Python 3.14.0 / Tk 8.6 |
| NumPy / SciPy / Matplotlib / RocketCEA | 2.4.2 / 1.17.0 / 3.10.8 / 1.2.3 |
| PyInstaller / hooks version | 6.21.0 / 2026.6 |
| `LPA.exe` 크기 / 서명 | 41,183,600 bytes / Authenticode 미서명 |
| `LPA.exe` SHA-256 | `E8F8671492A84D2EAE7860638776AF7178277D31A02FD65CB4C2844C5BA32B15` |
| 단일 EXE 격리 smoke | `PATH=C:\Windows\System32`, 별도 실행 폴더, 한글·공백 profile에서 `rocketcea + Bartz` 분석 완료 |
| 기준 project 파일 | 기본 LOX/RP-1 smoke project |
| Medium vs High peak `Twg` 차이 | |
| 미해결 warning / 승인자 | 미서명 배포본의 SmartScreen 가능성; 물리적 clean target PC/VM 최종 승인은 별도 수행 |

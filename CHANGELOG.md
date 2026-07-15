# LPA 변경 이력

모든 시각은 대한민국 표준시(KST, UTC+09:00) 기준입니다.

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

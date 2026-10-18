# VS Code 시작 중단 확인 및 0.16.0b2 Beta 수정

기록일: 2026-10-19 KST. 사용자가 `python -u main.py`로 실행할 때 Matplotlib `_backend_agg`의 import 도중 `KeyboardInterrupt`가 표시되는 사례를 보고했다.

## 확인 결과

- PATH의 Python은 **C:\Python314\python.exe**, CPython **3.14.0 64-bit**였다. Matplotlib **3.10.8**은 보고된 것과 같은 사용자 site-packages에서 로드되었다.
- 최초 재확인에서 같은 Python의 TkAgg import는 **1.050 s**, 뒤이은 `lpa.app` import는 **0.329 s**에 완료됐다. 빌드 가상환경에서도 각각 **1.820 s / 0.279 s**에 완료됐다. import 실패나 지속적인 정지는 재현되지 않았다. 이 수치는 해당 시점의 측정값이며 cold-start 성능 보장은 아니다.
- `KeyboardInterrupt`는 실행 중단을 나타낸다. traceback의 import 위치만으로 Matplotlib 패키지 손상이나 ABI 오류를 확인할 수 없다. 원래 실행에 중단 신호를 보낸 주체는 해당 traceback으로 특정할 수 없다.
- 기존 `lpa.app.run()`은 mainloop 안의 중단만 처리했다. Matplotlib import와 GUI 생성은 그 포착 범위 밖이었다.
- 실행에 쓰인 사용자 Python에는 **ht / fluids가 없었다**. GUI import는 열 solver를 지연 로드하므로 정상 완료되지만, Beta의 2상 계산 의존성이 갖춰진 환경은 아니었다. 이는 제공된 KeyboardInterrupt의 직접 원인으로 단정하지 않는다.

## 적용

1. `main.main()`의 시작 단계 전체에서 `KeyboardInterrupt`를 포착한다. 로그에 중단을 기록하고 **130**을 반환한다. 기존 mainloop의 정리 동작은 유지하며, 실제 ImportError 등은 숨기지 않는다.
2. 시작 로그에 Python 버전과 실행 파일 경로를 남긴다. 기본 로그는 `%LOCALAPPDATA%\LPA\logs\lpa.log`다.
3. 사용자가 실행한 동일 Python에 `python -m pip install --user --requirement requirements.txt`를 수행했다. 누락됐던 **ht 1.2.0 / fluids 1.3.1**이 설치됐고 기존 고정 버전은 유지됐다. `pip check`는 실행 Python과 빌드 가상환경 모두 통과했다.
4. README에 VS Code Python 확장의 interpreter 선택과 Code Runner의 별도 executor/PATH 설정을 설명하고, 같은 Python으로 설치와 실행을 수행하는 절차를 추가했다. 개인 VS Code 설정은 변경하지 않았다.
5. 버전을 **0.16.0b2 Beta**, Windows 고정 버전을 **0.16.0.2**로 올린다. 열전달 식·물성 모델의 변경은 없다. b1 검증 기록은 이전 버전 이력으로 보존한다.

## 검증 기록

원본 기록은 [startup_beta_outputs_0160b2](startup_beta_outputs_0160b2/)에 보존한다. 후속 import 시간은 패키지를 먼저 불러온 warm 상태이므로 최초 측정과 구분한다.

- 시작 import 중단, GUI 생성 중단, 정상 실행, 실제 import 오류 유지, 실제 스크립트 진입 시 exit 130·stderr 비움·로그 기록을 회귀시험으로 확인한다.
- 사용자가 실행한 **C:\Python314\python.exe -u main.py**로 실제 창 생성·응답·정상 닫기를 시험한다. VS Code 자체 UI를 자동 조작한 시험은 아니다.
- `tools/smoke_windows_release.ps1`은 source Python과 frozen EXE를 구분해 자신이 만든 프로세스만 확인·종료한다. Windows PowerShell 5.1에서 정상 종료 뒤 ExitCode를 보존하도록 process handle을 유지한다.
- 버전별 원본 시험·빌드·번들 검사·실행 결과와 해시는 [VALIDATION.md](VALIDATION.md)의 b2 항목에 실제 완료 결과로 기록한다. clean VM 전체 계산이나 VS Code 확장 조합 전체 검증은 수행하지 않는다.

# LPA 0.16.0b1 Beta

LNG의 150 K·25 bar 상태 선택 오류와 RPA 대비 큰 Bartz 열전달 차이를 수정하고, 순수유체의 포화 2상 채널 계산과 영역 표시를 추가했습니다. 기존 Rao 형상·자동 O/F 및 이전 미커밋 개선도 모두 포함합니다.

- Bartz: 유동 chemistry와 분리한 frozen chamber Cp/Pr/mu/gamma, 실제 상류 목 곡률 R1 적용. RPA fixed-wall 3지점 비교 차이 3% 이내.
- 물성: 실제 bubble/dew 경계와 bracket PH 역산, EOS/transport 출처·범위·상별 물성·질량건도, 선택적 외부 REFPROP 지원.
- 순수유체 2상: Li-Wu/Chen-Bennett, Lockhart-Martinelli 마찰, homogeneous 가속·운동에너지 수지. 온도 그래프의 2상 음영과 quality/regime CSV.
- 중단 처리: 건도·상관식 범위·혼합물·물성 실패를 명시하고 미계산 값을 보존. 중단된 상류를 건너뛰는 직렬 회로 계산 차단.
- 진단: rotating runtime 로그와 수치 수렴/계산 완료 station 수 분리. README·CHANGELOG·검증·방법 근거 문서 최신화.

검증: **598개 전체 시험 통과**, Windows EXE 빌드 및 시작/정상 종료, 35개 모듈 소스 일치, 추출 번들의 CEA/EOS/단상·2상 계산 확인. 자세한 기록은 `docs/VALIDATION.md`와 `docs/THERMAL_BETA_2026-10-19.md`를 참조하십시오.

**Beta 적용범위:** 순수유체의 pre-dryout 포화 비등 상관식이며 실제 엔진 검증판이 아닙니다. LNG/수용액 혼합물은 2상 상태와 질량건도를 검출·표시하지만 혼합물 비등 열전달은 중단합니다. CHF/dryout·subcooled boiling·초임계 HTD는 미검증/미지원입니다. 건도 0.7은 계산 제한이며 안전 여유나 dryout 예측점이 아닙니다. REFPROP는 별도 설치·사용권이 필요합니다.

Windows x64 ZIP에는 LPA.exe와 README 및 third-party license notices가 들어 있습니다. RocketCEA 1.2.3 소스와 SHA256SUMS도 함께 제공합니다. 저장소와 다운로드는 기존 비공개 접근 권한을 유지합니다.

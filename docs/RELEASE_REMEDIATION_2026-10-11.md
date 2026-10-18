# LPA 0.14.0 배포 검토 수정 및 신뢰도 평가

대상: 2026-10-11의 LPA 0.13.0 작업트리 검토에서 확인한 **P1 5건, P2 23건, P3 6건 — 총 34건**과 열전달 method별 추가 수정·검증 사항. 기존 미커밋 작업을 보존하면서 수정했다. 날짜는 KST 기준이다.

후속 **0.15.0**은 이 보고서의 수정 사항을 보존하며 자동 O/F 목적을 **Maximum theoretical vacuum Isp**로 변경했다. 해당 변경·독립 검증·신뢰도 및 새 배포 결과는 [자동 O/F 후속 적용 기록](OF_OPTIMIZATION_REVIEW_2026-10-11.md)과 [검증 기록](VALIDATION.md)의 0.15.0 항목을 참조한다.

이 문서는 구현 오류의 수정, 계산의 적용범위 통제, 실제 물리 정확도의 확보를 구분한다. 시험을 통과했다는 것은 아래 명시한 수식·상태 전달·회귀 동작의 근거다. 실제 엔진의 열유속·벽온도·수명 오차를 인증하는 근거는 아니다.

## 평가 기준

| 평가 | 의미 |
|---|---|
| 구현 신뢰도 높음 | 재현 결함의 회귀시험 및 독립 식/공개 API 대조가 있고 현재 통합시험을 통과한 범위 |
| 구현 신뢰도 중간 | 진단·근사·적용범위 제한은 확인했으나 넓은 운전영역의 정량 정확도 근거는 부족한 범위 |
| 물리 신뢰도 중간 | 예비 설계의 지정 적용범위에서 문헌 식/EOS와 일치하며 해당 엔진의 실측 보정은 없는 범위 |
| 물리 신뢰도 제한 | screening 근사 또는 미지원 모델. 수렴해도 실제 설계 적합성을 주장할 수 없는 범위 |

`physical_validity`는 `valid / screening / invalid / unsupported`, 수치 수렴은 `converged`, 연결 반복은 `coupled_converged`로 별도 기록한다. `valid`는 **현재 구현한 모델의 입력·상태 조건이 허용됨**을 뜻한다. 장치 전체의 안전성이나 실험 검증 완료를 뜻하지 않는다. UI와 원본 CSV는 상태, 전체 경고, 출처를 함께 노출한다.

## P1 수정 5건

| ID | 원래 문제 | 수정 및 검증 | 자체 평가 |
|---|---|---|---|
| P1-01 | 압력·상·임계 조건 없이 액체 물성을 모든 상태에 사용 | `at_state(T,p)` / `at_enthalpy(h,p)`와 CoolProp HEOS 경로를 추가했다. 포화/임계/가스/초임계 상태를 기록한다. 벽 비등·pseudocritical peak 횡단은 결과 전체를 미지원으로 제한한다. bulk 2상·EOS flash 실패·압력 소진은 행진을 중단하고 후속 station을 NaN으로 남긴다. `test_release_thermal_fixes.py`의 순수 유체 API 대조, 비등·압력 고갈·HTD 회귀로 확인했다. | 구현 높음. 순수 유체 EOS 물성 중간; 2상/HTD 열전달은 제한. EOS가 있어도 해당 열전달 모델이 검증되는 것은 아니다. |
| P1-02 | 박리/비초크 성능을 Cf=0.02로 대체하고 사이징 | 임의 양수 하한을 제거했다. 부착 초음속 모델의 범위를 벗어나면 성능은 NaN/미지원 경고이며 명목추력 사이징을 거부한다. 직접 직경 해석은 지원되는 진공 성능과 미지원 외압 성능을 구분한다. 박리·역압·사이징 시험으로 확인했다. | 구현 높음. 부착 유동 중간; 박리 성능 자체는 미지원. |
| P1-03 | Film 오리피스가 Regen 입구압으로 산정 | 연결 회로 **최종 출구의 T/P**와 실제 주입 위치의 가스압을 사용한다. 역압·공급압 부족·알려진 flashing 조건을 차단한다. 기체는 압축성/초크 식과 gamma·Z 제한을 적용한다. 독립 액체 Cd 및 NASA 초크 질량유속식으로 대조했다. | 구현 높음. 액체 Cd/근이상기체 오리피스 중간. 연결은 상태 참조이며 실제 bleed 배관 질량수지를 구현한 것이 아니다. |
| P1-04 | Regen/Film/Radiation CRUD 후 변경 유실 | 추가·편집·복제·삭제를 dirty 추적과 입력 revision에 연결했다. New/Open/Close에 필요한 저장 변경 처리가 동작한다. 네 가지 CRUD 회귀시험 통과. | 구현 높음. |
| P1-05 | 이전 분석 완료 결과가 새 입력에 표시 | 입력 snapshot/revision을 고정하고 입력 변경 시 결과를 지우며 오래된 future 완료 결과를 폐기한다. New/Edit/Clear 중 완료 및 결과 무효화 시험으로 확인했다. | 구현 높음. |

## P2 수정 23건

| ID | 원래 문제 | 수정 및 검증 | 자체 평가 |
|---|---|---|---|
| P2-01 | Frozen Isp와 Pe/MW/gamma 조건 불일치 | 모든 관련 CEA getter에 동일 frozen flags를 전달했다. 실제 LH2/LOX throat-frozen Pe·MW·gamma·Mach 및 station transport를 공개 getter와 대조했다. | 구현 높음, CEA 모델 내 정합성 중간. |
| P2-02 | 입력 동결 위치 숫자 무시 | 신규 UI는 shifting/throat freezing만 제공한다. A/At=1 이외 legacy 근사에는 경고를 남긴다. FAC에서 chamber-frozen의 실제 CEA station이 유효하지 않아 명시적으로 거부한다. legacy 입력을 조용히 다른 조건으로 계산하지 않는다. | 구현 높음. 임의 위치 동결과 FAC chamber-frozen은 미지원. |
| P2-03 | 직접 길이가 수축각/원호 곡률을 바꾸지만 요청값 보고 | 직접 Lc/Lcyl의 길이 우선 타원호 형상을 유지하되 실제 접선각과 양 끝 곡률 R1/R2를 보고한다. 요청 곡률·원호 종류·경고를 metadata에 분리한다. 독립 미분 곡률 및 각도 시험으로 확인했다. | 구현 높음, 형상 계산 높음. 직접 길이의 타원호는 자동 최적 설계가 아니다. |
| P2-04 | 저팽창 cone의 출구면적 오류 | 목 원호와 지정 출구/각도가 양립하지 않으면 명확한 기하 오류를 반환한다. 가능한 형상의 면적과 접선은 그대로 보존한다. 극저팽창 회귀시험 통과. | 구현 높음, 기하 높음. |
| P2-05 | divergence factor에 불필요한 sqrt | 에너지 효율에 lambda²를 적용해 운동량 배율이 `(1+cos(theta))/2`가 되게 했다. 15/25/40°의 독립 식 대조. | 구현 높음, conical 근사 중간. Bell의 추력 최적성은 실측 검증 없음. |
| P2-06 | Film 회수가 압력추력까지 확대 | 회수 계수는 운동량 항에만 적용하고 `(Pe-Pa)Ae`는 보존한다. 여러 Film 비율에서 외압 변화의 추력 기울기를 독립 면적과 비교했다. | 구현 높음, 회수율 경험 근사는 제한. |
| P2-07 | 반응효율 후 연속방정식 불일치 | eta를 Cstar 효율로 정하고 온도 closure에 eta²를 적용했다. FAC의 Cstar/Pinf와 입력 Pinj 기준 차이도 보정했다. 목의 rho·u와 m/A, eta 100/98/50%를 대조했다. | 구현 높음, 효율 상태 보정의 물리 신뢰도 제한. ideal CEA 조성/Cp/transport를 유지한 eta² 온도 보정이며 재평형 계산이 아님을 결과에 경고한다. |
| P2-08 | 출구 MW/gamma·공기 transport를 축방향 전체 적용 | CEA의 실제 station P/T/h/s/Cp/MW/gamma/mu/Pr와 H2O/CO2 조성을 배치 수집한다. equilibrium/frozen 상태 정의를 보존한다. 실제 CEA getter·동시 호출 대조. | 구현 높음, Bartz의 Cp/반응 경계층 선택 및 열유속 예측은 중간. |
| P2-09 | fallback을 보수적이라 표현 | conservative 표현을 제거했다. fallback 출처·screening 경고를 sweep에도 전달하며 require-CEA 정책을 유지한다. 실패 backend와 sweep 시험 통과. | 구현 높음. fallback 물리 신뢰도 제한; 오차의 방향을 보장하지 않는다. |
| P2-10 | Film/Regen 연결이 한 번 반복 후 수렴 표시 | 최종 Regen 출구 상태와 Film을 외부 반복으로 수렴시키고 내부 벽 수렴/연결 수렴을 분리했다. 연결 온도 불일치 및 반복 제한 시험으로 확인했다. | 구현 높음, 액체 Film 현상은 제한. |
| P2-11 | 외부 Film 유량을 엔진 Regen에 포함 | 엔진 산화제/연료 Regen의 상대 유량은 외부 Film을 제외한 실제 엔진 공급류 질량으로 정했다. 30% 외부 Film과 독립 mass ledger 시험으로 확인했다. | 구현 높음. 실제 Film bleed·mixer·분기 회로는 별도 모델 없음. |
| P2-12 | 세그먼트 경계 셀의 겹치는 길이 누락 | 중심 위치와 무관하게 모든 셀 교집합을 적분한다. 1 mm 및 인접 세그먼트의 길이 분할·표면 열수지 보존 시험. | 구현 높음, 적분 보존 높음. |
| P2-13 | bulk 행진에 벽 인접 Cp 재사용 | `h_out=h_in+Q/m`와 출구압의 h-p flash를 사용한다. 대류용 film-temperature 물성과 bulk h를 분리한다. 독립 EOS 입·출구 엔탈피 수지 시험. | 구현 높음, 단상 에너지 수지 높음. |
| P2-14 | thermal 재격자에서 정확한 목 유실 | thermal mesh가 contour와 달라도 목 break point와 실제 반경을 보존한다. 서로 다른 해상도에서 목 A/At=1 확인. | 구현 높음, 기하 높음. |
| P2-15 | 공급 상태/Regen 출구 h가 CEA에 미반영 | 산화제/연료 공급 T/P 네 선택 필드와 화학 생성엔탈피+EOS 상대 sensible/mixing h 카드를 추가했다. 선택적 Regen feed feedback은 완화 반복·온도/압력 허용치·내부 수렴 gate로 제한했다. 저장 roundtrip, 독립 카드 h 변화 및 반복 실패 시험. | 구현 높음. pure EOS 중간, H2 spin/IPA/H2O2/kerosene·복잡 회로는 제한. 기본은 피드백 OFF이며 미연계 경고를 제공한다. |
| P2-16 | LNG 성분마다 서로 다른 기준온도 | 모든 성분 카드를 공통 111.66 K/5 bar 혼합물 기준으로 생성하고 실제 T/P 입력을 지원한다. 조성별 HEOS 혼합물 상대 h를 총 화학 h에 더한다. 액체 phase root 및 카드 가중 엔탈피 검증. | 구현 높음, 실제 LNG lot·선택기화·혼합물 transport는 제한. |
| P2-17 | 분해/coking을 비반응 물성으로 암묵적으로 허용 | H2O2/N2O의 반응 안정성, 탄화수소 침착/열분해/수명 모델 부재를 물리 경고와 capability에 명시한다. 보편 온도 안전한계를 새로 만들지 않았다. 관련 coolant/material 진단 시험. | 진단 구현 높음. 분해/coking 예측은 미지원. |
| P2-18 | TBC/roughness 오류 기본값 대체, count 절삭 | 활성 필드의 strict finite/정수 검증을 UI·normalizer·core model에 적용했다. 비활성 필드는 계산에 사용하지 않는다. 문자열/NaN/Inf/60.9/boolean 회귀시험. | 구현 높음. |
| P2-19 | Pc/O/F NaN 통과, sweep NaN/Inf 예외 | 공통 검증 경로에서 오류 메시지로 처리한다. optional T/P와 범위·points도 엄격히 확인한다. UI와 API invalid-input 시험. | 구현 높음. |
| P2-20 | 같은 이름 Regen의 연결 ID 변경 | 표시 이름과 내부 선택 ID를 분리하고 기존 선택 ID를 우선 보존한다. 중복 이름 roundtrip/편집 시험. | 구현 높음. |
| P2-21 | 손상 Open 후 일부 입력/경로 변경, 이전값 유입 | 파일 구조 검증→독립 기본값 migration→일괄 적용, 실패 rollback을 구현했다. Save는 임시 파일→원자적 교체로 기존 파일을 보존한다. 손상/legacy/원자적 저장 실패 시험. | 구현 높음. |
| P2-22 | 일부 경고만 표시, 수렴만 강조 | 모든 결과 페이지에 전체 경고·모델/출처 조회 및 복사와 별도 물리 상태를 제공한다. 없는 성능은 0 대신 dash, 없는 thermal 곡선도 렌더한다. 5개 초과 경고·NaN 결과 UI 시험. | 구현 높음. UI가 물리 정확도를 검증하는 것은 아니다. |
| P2-23 | 확대 글꼴에서 단위/표 헤더 잘림 | 글꼴 및 실제 값으로 최소 열 폭을 측정하고 label wrapping·수평/필요 세로 스크롤·metric 재배치를 적용했다. Tk scaling 1.333/1.667/2.0, 1080×700/1460×900, 8페이지 측정. | 구현 높음. 실제 Windows DPI 전환은 별도 검증 필요. |

## P3 수정 6건

| ID | 원래 문제 | 수정 및 검증 | 자체 평가 |
|---|---|---|---|
| P3-01 | Radiation 중복 우선순위 경고/실제 불일치 | 뒤 세그먼트가 우선하도록 계산을 경고와 일치시켰다. 두 중복 세그먼트 결과를 후자 단독 결과와 대조했다. | 구현 높음. |
| P3-02 | BLC 표시 선택과 sweep 기준 불일치 | `Display film correction`의 공유 상태를 성능·스로틀·외압/고도 결과에 일괄 적용한다. with/without 두 데이터와 warnings를 보존한다. 공유 선택 시험. | 구현 높음. |
| P3-03 | 같은 높이 카드 아래 공간 낭비 | 큰 글꼴/좁은 폭에서는 Performance와 Mass Flow를 세로로 배치하고 내용 높이로 배치한다. configure 반복으로 GUI가 멈추는 추가 결함도 제거했다. | 구현 높음, 대용 배율 범위에서 확인. |
| P3-04 | 원본 thermal station/최댓값 위치/경고 export 부재 | smoothing/대표점 축약 없이 모든 station의 x·온도·열유속·냉각 상태·phase와 수렴/물리 상태/전체 경고/출처를 CSV로 내보낸다. peak 위치는 원본 x/열값에서 재현 가능하다. Unicode 파일 및 모든 행/진단 export 시험. | 구현 높음. |
| P3-05 | Help frozen 설명과 실제 동작 불일치 | Help/입력 선택/validation/README를 shifting 및 throat-frozen 지원으로 맞췄다. FAC chamber-frozen 차단과 legacy warning을 명시한다. | 구현 높음. |
| P3-06 | 극단 Mach 역산 bracket 실패 미검사 | 로그 형태의 면적 관계와 adaptive bracket, 유한 입력/유효 gamma 및 bracket 실패 검사로 바꿨다. A/At=1e100 양 branch와 invalid-input 회귀시험. | 구현 높음, 상수 gamma 역산 자체 높음. 극단 입력의 실제 노즐 모델 정확도는 별개다. |

## 열전달 method의 추가 수정·검증

| Method | 수행한 수정과 검증 | 결과 및 현실과의 차이·자체 평가 |
|---|---|---|
| Bartz | SI 식을 별도 코드로 재구성해 sigma/회복온도/곡률/수송계수를 대조한다. 국소 CEA transport를 사용하고 압력/Cstar 기준을 일치시켰다. GOX/GCH4 기준 audit, 곡률·물성 민감도, 120/300/700 station 비교를 실행한다. | 식 구현 높음. 관측 열유속과 동일 입력의 외부 열시험 대조는 확보되지 않았다. equilibrium Cp가 반응 경계층의 유일한 정답은 아니다. 실제 엔진 예측 중간/조건별 보정 필요. |
| 채널 대류·Darcy/Haaland | 사각채널 aspect ratio의 laminar Poiseuille/Nu를 적용한다. square duct 독립 값, Re·Pr·entry-length·roughness 적용범위 진단, 압력 감소·소진 차단을 확인했다. | 구현 높음. fully developed 단상 분포 손실이다. 단면별 가열 경계, 개발 유동, 가속 압력손실, manifold/bend/local K 및 유량 불균등은 계산하지 않으며 screening 경고/capability로 남긴다. |
| Regen 벽·리브 | hot/coolant 면적 비와 리브 tanh(mL)/(mL) fin efficiency를 적용했다. 원통벽 log(rout/rin) 및 TBC 표면의 열유속 변환, 작은 두께/fin 극한, 독립 에너지 수지 검증. | 구현 높음. closeout·리브·벽 전체의 2D/3D 전도와 축전도·채널간 분배는 없다. 보정된 1D 모델의 물리 신뢰도 중간. |
| Radiation | 외벽 방사 면적과 원통 저항을 반영하고 중복 우선순위를 고쳤다. CEA H2O/CO2 조성·분압/기하 광로 proxy를 metadata에 기록했다. epsilon 변경 시 벽·냉각제를 다시 푸는 민감도 API/audit을 제공한다. | Stefan–Boltzmann/면적 구현 높음. 기본 epsilon=0.08은 여전히 gray screening parameter다. 분광/WSGG/soot 광학/Film 복사 차폐를 실제로 계산한 것으로 주장하지 않는다. 민감도 결과도 확률적 오차 범위가 아니다. |
| Film | 연결 Regen의 최종 출구 T/P를 참조하고 Film–Regen 반복의 수렴을 분리했다. 액체/기체 상과 chemistry-dependent 모델 부재를 판정한다. 운동량/압력추력·초크 restriction·연결 온도를 독립 대조했다. | 연결/수지 구현 높음. 지수 shielding은 coolant 종류에 따른 잠열·증발·주입 운동량·coverage를 풀지 않는다. 액체 Film 물리 신뢰도 제한. 실제 Regen 유량에서 Film을 뽑는 split-flow는 미지원이며 feed-feedback 조합을 차단한다. |
| 재료·TBC | k(T) 표 범위 초과와 screening curve 출처를 진단한다. cylindrical coating/wall flux 연속성과 표 범위/출처 export를 검증했다. | 구현 높음. 표 밖 끝값 clamp는 유지하되 경고한다. 실제 재료 lot/열처리/적층 방향/코팅 접촉저항·박리/온도 의존 emissivity·강도·수명은 검증되지 않았다. |
| Ablative·heat sink·비정상 | 결과의 model_capabilities에 transient wall storage/ablation/axial conduction/structural life 미지원 상태를 기록한다. 미지원 capability export 시험. | 적용범위 표시 높음. pyrolysis·ablation·점화/정지·열응력·수명 계산 구현과 실험 검증은 수행하지 않았다. |

### 추진제별 상태 처리

| 유체 | 0.14.0 상태/에너지 처리 | 남는 제한 |
|---|---|---|
| O2, CH4, H2, N2O, Propane, Water, 순수 Ethanol | HEOS T/P 및 h/P, 임계·포화·기체/초임계 판정. 순수 유체 독립 공개 API 대조. | 벽 비등/CHF/dryout·초임계 HTD·reactive stability는 미지원. H2 명시 공급 상태는 normal-H2 공통 화학 h anchor를 사용하며 para/ortho spin conversion은 계산하지 않는다. legacy LH2 기준 카드는 보존하고 별도 경고한다. |
| Ethanol/Water | 실제 mass fraction의 HEOS 혼합물 h/phase, bubble/dew 근거의 compressed-liquid root 선택과 엔탈피 역산 | transport가 지원되지 않는 혼합물은 별도 screening 혼합 근사. 농도별 실측 검증과 2상 분별 기화 없음. |
| LNG | 지정 조성의 HEOS 혼합물, 공통 공급 상태의 h, 안정 액체 root/flash 확인 | 실제 lot 조성·선택 기화·phase envelope/transport·HTD 검증 부족. |
| IPA/Water, H2O2/Water | 명시된 근사 물성/공급 sensible h와 출처·screening 경고 | 검증된 EOS/VLE·발열 분해 모델 없음. 순수 유체 임계값을 혼합물의 안전한계로 사용하지 않는다. |
| RP-1, Jet A-1 | 공학 근사와 해당 범위/출처 경고 | 실제 혼합연료 EOS·coking/deposit 저항·수명 없음. |

### 검증 자료

신규 회귀시험은 `tests/test_release_performance_fixes.py`, `test_release_thermal_fixes.py`, `test_release_integration_fixes.py`, `test_release_independent_integration.py`, `test_release_ui_fixes.py`에 보존한다. 독립 검증은 생산 함수를 복제한 expected 값만 사용하지 않고 NASA 식, 공개 CEA getter, 별도 HEOS 상태, 해석적 곡률·fin·원통 저항·셀 교집합으로 대조한다.

최종 통합시험과 배포 파일 해시는 VALIDATION.md의 0.14.0 기록에 보존한다. 과거 `THERMAL_AUDIT_2026-07-21.md` 및 `PROPELLANT_AUDIT.md`의 수치는 당시 버전의 이력이며 현재 EOS 검증 결과와 혼용하지 않는다.

### 실제 열전달 검증 결과

산출물은 [0.14.0 thermal audit 자료](thermal_audit_outputs_0140/)에 보존했다. 다음 값은 소프트웨어/EOS 대조용이며 열시험 실측치가 아니다.

| 검증 | 결과 | 해석 |
|---|---|---|
| 실제 GOX/GCH4 CEA + 독립 Bartz 재구성 | 최대 상대 차이 **8.522×10⁻⁷** | SI 변환·factor·회복온도·sigma의 수치 대조. 실제 열유속의 측정 정확도는 의미하지 않는다. |
| 동일 audit, 물 25 bar, 300 station | **97 station** 계산 후 bulk 2상에서 중단. `unsupported`, 유효 단상 부분 열부하 **372,727.070 W**, 엔탈피 잔차 **5.82×10⁻¹¹ W** | 과거 단상 근사에서 전 구간 유한 온도가 나온 조건을 이제 미지원으로 검출한다. 남은 NaN 구간을 제외한 peak를 전 엔진 peak로 해석하면 안 된다. |
| 350/700/1400 station × epsilon 0/.02/.08/.16 | 12조건 모두 phase 제한 **unsupported**. epsilon=.08의 solved station은 **112/224/448**, 계산된 목 Twg는 **871.013/871.128/871.169 K** | 격자 수렴 추세가 있어도 누락된 2상 구간의 정확성이 확보되는 것은 아니다. [전체 원본](thermal_audit_outputs_0140/audit/axial_convergence.csv). |
| 8 coolant의 독립 원통/정상상태 수지 | H2O/Et70/LNG/H2O2는 screening; LOX/CH4/H2/N2O는 벽 비등 또는 HTD로 unsupported. 최대 절대 에너지 잔차 **5.78×10⁻⁵ W** | gas 상태는 지정 상수 모델이다. unsupported에서도 비교용 단상 후보가 남을 수 있으므로 상태 판정과 함께 읽어야 한다. [case matrix](thermal_audit_outputs_0140/coolant_case_matrix.csv). |
| GOX/GCH4/GH2, 300 K, 10/30/100 bar | 밀도와 phase가 압력에 따라 달라짐. GOX rho **12.907/39.171/134.574 kg/m³**, GH2 **0.8035/2.3825/7.6254 kg/m³** | 온도만의 이전 액체/기체 근사를 제거했는지 확인. [pressure matrix](thermal_audit_outputs_0140/pressure_state_matrix.csv). |
| 3400 K gas, epsilon .02/.08/.16의 완전 재해석 | Twg peak **526.051/528.333/531.376 K**, coolant outlet **310.826/311.028/311.297 K** | 주어진 gray parameter 시나리오의 민감도. 분광 emissivity 검증이나 통계적 불확실성 범위는 아니다. [원본 JSON](thermal_audit_outputs_0140/thermal_method_benchmarks.json). |
| 실제 CEA+CoolProp 공급 피드백 | 부분 5 mm Et70 엔진 연료 회로, **8회** 수렴, 출구 **313.326 K / 249.2279 bar**, ΔT **0.00919 K**, Δp **0.000486 bar** | 외부 반복의 실제 통합 실행 근거. 벽온도는 **3/120 station**만 예측하고 나머지 미해석 및 screening 경고 유지. 전 엔진 열 정확도 근거가 아니다. [전체 입력·반복·결과](thermal_audit_outputs_0140/partial_feed_feedback.json). |

LNG의 과거 실패점 111.744 K/60 bar에서는 안정 액체 root로 rho 약 **447 kg/m³**, Cp 약 **3257 J/(kg·K)**를 복구했다. 혼합물의 자동 flash가 비정상적으로 큰 h/Cp를 반환한 경우를 정상 단상 해답으로 승인하지 않는다. 혼합물 phase root와 엔탈피 역산에 회귀시험을 추가했으며 실제 lot와 넓은 phase envelope 검증은 여전히 필요하다.

## 최종 판정과 남는 검증

최종 소프트웨어 회귀시험은 **525 passed / 45.64 s**이며 오류와 skip은 없다. 0.14.0 EXE/ZIP을 재빌드하고 현재 소스 33개 모듈·main·리소스와 일치함을 확인했다. 실행/응답/정상 종료와 번들 추출 EOS·CEA·열수지 계산도 통과했다. 구체적 해시와 시험 모드는 [배포 검증 기록](VALIDATION.md#검증-기록-0140)에 보존했다.

34건의 구현 결함과 표시·진단 보완의 신뢰도는 명시한 회귀 범위에서 **높음**이다. 열전달 추가 요구의 수식/수지/상태 진단은 수행했지만 **모든 실물 현상 모델이 구현되거나 실험으로 검증된 것은 아니다**. 정상 단상 EOS·기하·수지는 예비 설계 근거가 있고, 경험 효율/Film, 혼합물 transport, 고정 gray emissivity, 2상/HTD/분해/coking/closeout·매니폴드·비정상/수명은 정량 설계 신뢰도가 제한되거나 미지원이다. 새로운 보편 안전온도나 임의 경험계수를 만들어 이를 검증 완료로 표시하지 않았다.

별도 clean PC/VM 전체 계산, 실제 OS DPI 전환, 코드 서명/보안 검사, 재배포 소스 제공 방식과 실기·CFD/FEA 검증은 완료되지 않았다. 이것들은 현재 소프트웨어 시험의 통과로 대체할 수 없다.

## 근거 자료

- [RocketCEA 1.2.3 공개 API](https://rocketcea.readthedocs.io/en/stable/functions.html), [박리와 ambient 성능 구분](https://rocketcea.readthedocs.io/en/stable/ambient_isp.html), [공급 온도/엔탈피 조정](https://rocketcea.readthedocs.io/en/stable/temperature_adjust.html).
- [CoolProp 8.0.0 상태·상 지정·기준 엔탈피](https://coolprop.org/coolprop/HighLevelAPI.html). 상을 임의로 강제하지 않고 bubble/dew로 확인된 compressed-liquid 영역에서만 액체 root를 선택한다.
- [NASA 추력식](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/rocket-thrust/), [NASA 압축성 질량유속/초크 식](https://www.grc.nasa.gov/www/k-12/airplane/mflchk.html).
- [NASA 채널·리브/closeout 연구](https://ntrs.nasa.gov/api/citations/20240003814/downloads/9654_COOPER_May2024JANNAF.pdf), [NASA 가스 복사 연구](https://ntrs.nasa.gov/api/citations/20080002105/downloads/20080002105.pdf), [DLR 초임계 열전달 실험](https://www.jstage.jst.go.jp/article/tastj/19/1/19_19.96/_article). 모델의 누락과 검증 필요성을 평가한 근거이며 해당 상세 모델 전체를 구현했다는 뜻은 아니다.

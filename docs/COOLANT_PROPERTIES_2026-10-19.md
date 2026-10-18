# 냉각제 EOS, flash, 물성 범위 — 2026-10-19

이 문서는 `lpa/thermal/coolants.py`의 물성 구현과 검증 범위를 기록한다. 열전달 상관식의 적용 가능 여부는 별도 판정이다. 물성값이 계산된다는 사실만으로 비등·CHF·dryout·초임계 열전달 모델이 검증되었다고 판단하지 않는다.

## LNG 150 K / 25 bar의 비정상 root

기본 LNG는 CH4/C2H6/C3H8/n-C4H10/N2의 몰분율 0.94/0.047/0.008/0.002/0.003을 사용한다. CoolProp 8.0.0의 자동 HEOS PT flash는 150 K / 25 bar에서 다음 비정상 branch를 선택했다.

| 평가 | phase | 밀도 kg/m³ | Cp J/(kg K) | h J/kg | k W/(m K) |
|---|---|---:|---:|---:|---:|
| 수정 전 자동 PT | gas | 120.894534 | 1,217,238.13 | -3,491,925.306 | NaN, screening 대체 |
| 동일 조성·T/P, 액체 branch | liquid | 384.368775 | 3,657.602 | 118,399.834 | 0.140414 |

25 bar의 bubble 온도는 174.020299 K다. 20/30 bar, 150 K의 정상 액체 밀도는 각각 383.394586/385.320672 kg/m³이다. 수정 전에는 액체 root를 지정하기 위한 기준압력을 0.1 Pc 이하로 제한했으므로, 기준 bubble 온도 138.302609 K보다 높은 150 K를 액체로 입증하지 못했다.

구현은 subcritical pressure에서 **실제 압력의 bubble/dew flash**를 계산한다. bubble 아래는 liquid, dew 위는 gas root를 지정하고, 그 사이에서는 PQ flash의 quality를 bracket하여 목표 온도를 찾는다. near-critical 및 critical pressure 이상의 retrograde envelope는 일반적으로 입증하지 않는다. 해당 영역에서 낮은 기준압력의 bubble 온도보다 낮은 상태만 보수적으로 액체 root로 선택하며, 나머지는 명시적 진단을 남긴다.

단순한 Gibbs 최소값 판정으로 이 문제를 해결했다고 주장하지 않는다. 비정상 branch의 Gibbs 값이 정상 액체 branch보다 낮고 두 branch의 등온 압축성 미분도 양수였다. 검증 근거는 bubble 경계, 주위 압력의 밀도 연속성, 정상 액체 branch와의 비교 및 엔탈피 진행의 일관성이다. 독립 REFPROP 또는 실측값과 전체 flash 경로를 대조한 검증은 별도로 필요하다.

## PH 역산과 두 상 상태

혼합물 PH 역산은 bubble/dew의 h 범위를 이용한다. 단상은 입증된 liquid/gas 구간에서 온도 bracket + Brent 방법으로 풀고, 두 상 영역은 quality bracket + PQ flash로 푼다. 상경계를 가로질러 단일 Cp의 Newton 방법을 반복하지 않는다. 순수 유체는 CoolProp의 native PH flash를 사용한다.

`CoolantState`는 다음을 제공한다.

- `vapor_quality_mass_fraction`: 질량 기준 증기 건도. 혼합물 CoolProp의 몰 기준 Q를 각 상의 분자량으로 변환한다.
- `saturated_liquid`, `saturated_vapor`: `CoolantPhaseState`. 각 상의 밀도, Cp, k, 점도, h, T/P, 분자량, 음속, Cv 및 물성 대체 경고를 제공한다.
- `surface_tension_n_m`: 가능한 경우 EOS의 표면장력. 혼합물 등 미지원 상태에서는 NaN과 경고를 제공한다.
- `equilibrium_energy_residual_j_kg`: EOS bulk h와 질량 기준 상별 h 혼합값의 차이. 상대 오차가 1e-4를 넘으면 상태를 승인하지 않는다.
- `thermodynamic_source`, `transport_source`, `property_limits`: 열역학 EOS와 수송물성의 출처·제한을 분리한다.

두 상 bulk Cp/k/점도에는 유일한 평형 수송 정의가 없다. 기존 scalar 필드는 상별 값을 질량 가중한 **진단값**으로 남기며 관련 경고를 붙인다. 비등 상관식은 반드시 phase-resolved 물성을 사용해야 한다. 순수 유체 두 상의 h 혼합과 latent heat는 검증했다. 혼합물에는 temperature glide, 상별 조성 변화 및 별도 boiling 검증이 필요하다. Et70, 470 K / 25 bar에서 CoolProp PQ의 상별 에너지 closure 차이 약 14.57 J/kg(약 1.04e-5 상대)이 확인되어 진단으로 노출한다. 따라서 혼합물 두 상 thermodynamics 제공을 혼합물 boiling 상관식의 승인으로 해석하지 않는다.

공개 API:

```python
coolant_state(name, temperature_k, pressure_pa, *, backend="HEOS")
coolant_state_from_enthalpy(name, enthalpy_j_kg, pressure_pa,
                          *, temperature_hint_k=None, backend="HEOS")
coolant_state_from_quality(name, pressure_pa, vapor_quality_mass_fraction,
                          *, backend="HEOS")
coolant_saturation_pressure(name, temperature_k, *, backend="HEOS")
coolant_property_limits(name, *, backend="HEOS")
```

`coolant_saturation_pressure`는 순수 유체의 saturation pressure 또는 혼합물의 bubble pressure다. 계산할 수 없는 경우 NaN을 반환한다. `coolant_state_from_quality`는 유효한 PQ 상태를 요구하며 미지원 입력은 예외를 낸다. `CoolantPropertyModel.at_state/at_enthalpy`도 backend keyword를 지원한다.

## 온도·압력 한계와 transport

`CoolantPropertyLimits`는 backend, EOS Tmin/Tmax/pmax, 출처, 참고 URL, 개별 transport 제한을 제공한다. EOS 한계 밖 PT/PH 결과는 validated state로 반환하지 않는다. 실패 상태는 phase unknown과 EOS 실패 이유를 남긴다. 물의 경우 CoolProp의 2000 K 외삽 허용값 대신 IAPWS-95의 안정 유체 검증 상한 1273 K를 사용한다.

| 순수 유체 | EOS 온도 경계 K | EOS pmax MPa |
|---|---:|---:|
| H2O | 273.16–1273 | 1000 |
| O2 | 54.361–2000 | 80 |
| CH4 | 90.6941–625 | 1000 |
| normal-H2 | 13.957–1000 | 2000 |
| N2O | 182.33–525 | 50 |
| propane | 85.525–650 | 1000 |
| ethanol | 159.1–650 | 280 |

이 표는 EOS의 선언 경계다. 모든 T/P 조합, 응고 경계, 임계점 근처의 모든 물성 정확도를 보증하는 직사각형 검증 영역이 아니다. IAPWS-95의 검증 영역은 **융해선부터** 1273 K / 1000 MPa까지다. 혼합물의 freezing은 모델링하지 않는다. CoolProp의 혼합물 상한은 조성가중되어 순수 성분의 상한보다 높게 나타날 수 있으므로, 구현은 각 구성 성분의 Tmax/pmax 최솟값을 함께 적용한다. 예를 들어 Et70의 가중 Tmax 약 1355.9 K를 승인하지 않고 650 K로 제한한다.

`CoolantTransportLimits`는 개별 property의 온도·압력 한계를 따로 기록한다. 확인하지 못한 한계는 NaN이며 EOS 상한에서 임의로 유도하지 않는다. 순수 ethanol의 열전도도 기준상관식은 triple point–600 K, 245 MPa까지다. EOS가 620 K 상태를 계산하더라도 k의 검증 범위가 아니므로 명시적 screening 대체 경고를 남긴다. LNG에서는 현재 액체 branch의 viscosity가 HEOS에서 제공되지 않아 screening 대체가 남을 수 있다. EOS 밀도·h가 정상이어도 이 수송물성 한계는 사라지지 않는다.

## REFPROP 및 데이터 확대

`backend="REFPROP"` 또는 `"refprop"`는 CoolProp의 REFPROP backend를 사용한다. 별도 REFPROP 설치·라이선스·fluid files가 필요하다. 선택한 REFPROP가 없거나 실패하면 이유를 명시하고 unknown 상태로 반환하며 HEOS로 몰래 바꾸지 않는다. 실제 REFPROP DLL과의 비교 계산은 본 환경에서 수행하지 않았고, 미설치 동작은 회귀시험에서 검증했다.

LNG 데이터 확대 후보는 NIST EOS-LNG다. 주된 새 액체 밀도 데이터는 100–180 K / 최대 10 MPa이므로 150 K / 2–3 MPa 조건이 관심 범위에 들어간다. 이 모델의 밀도 근거를 점도·열전도도 정확도까지 확대 적용하지 않는다. 현재 HEOS를 EOS-LNG 자체라고 표기하지 않으며, 설치된 provider의 모델과 실제 LNG lot 조성을 확인한 대조가 필요하다.

### RP-1 surrogate의 실제 의존성

NIST 2009 RP-1 모델은 alpha-methyldecalin, n-dodecane, 5-methylnonane, heptylcyclohexane의 네 성분 surrogate다. 설치된 CoolProp 8.0.0 HEOS에는 이 중 n-dodecane만 있고 나머지 세 성분이 없다. 논문은 해당 성분들의 전용 EOS/transport REFPROP fluid files를 저자에게 확보하도록 명시한다. 따라서 몇 개의 임의 n-alkane으로 대체한 혼합물을 이 NIST surrogate라 부르는 provider는 추가하지 않았다.

RP-1, Jet A-1, IPA 및 H2O2는 현재 압력·상평형 검증 EOS가 없는 screening 모델이다. 검증된 외부 provider는 기존 `settings.coolant_properties`의 custom model 계약으로 연결할 수 있다. 가변 Cp provider는 일관된 기준의 h와 `at_state(T,P)`, `at_enthalpy(h,P)`를 함께 제공하고 phase를 밝혀야 한다. RP-1의 정확한 NIST provider를 활성화하려면 원문의 조성·성분 파일·혼합물 모델·transport 모델 확보와 수치 대조가 선행되어야 한다. 이는 현재의 단순 screening 값을 validated RP-1 물성으로 승격하지 않는다.

## 검증

`tests/test_coolant_phase_flash_regression.py`: 12 tests passed (`.venv-build/Scripts/python.exe -B -m pytest -q -p no:cacheprovider ...`).

- LNG 150 K, 20/24.9/25/25.1/30 bar: 액체 밀도 연속성, 독립 액체 branch와 h/밀도 비교, +2500 J/kg 가열 및 1000 Pa 감압 PH 진행.
- 물 25 bar 두 상: 질량건도, latent energy, 각 상의 k/점도 및 표면장력, PH 역산, saturation pressure.
- LNG/Et70: 액체 hint에서 두 상 상태로의 PH 역산과 mass-quality roundtrip.
- 순수 및 혼합물 EOS 범위 초과 거부, EOS와 conductivity 범위의 분리, REFPROP 미설치 시 명시적 실패, 미지원 RP-1의 screening 표시.

이는 물성 모듈 회귀검증이며 전체 엔진·열전달·구조 검증을 대체하지 않는다.

## 1차 자료

1. [CoolProp mixture model and supported flash pairs](https://coolprop.org/fluid_properties/Mixtures.html), [REFPROP interface](https://coolprop.org/coolprop/REFPROP.html).
2. [IAPWS-95 official release](https://iapws.org/technical-guidance/release/IAPWS-95).
3. [CoolProp ethanol EOS and transport references](https://coolprop.org/fluid_properties/fluids/Ethanol.html); Assael et al., ethanol conductivity reference correlation, [DOI 10.1063/1.4797368](https://doi.org/10.1063/1.4797368).
4. Thol et al., EOS-LNG (2019), [NIST publication record](https://www.nist.gov/publications/eos-lng-fundamental-equation-state-calculation-thermodynamic-properties-liquefied), [NIST full text](https://srd.nist.gov/jpcrdreprint/1.5093800.pdf).
5. Huber et al., RP-1/RP-2 surrogate models (2009), [NIST full text](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=900238), [DOI 10.1021/ef900216z](https://doi.org/10.1021/ef900216z).
6. [NIST REFPROP program and surrogate model context](https://www.nist.gov/programs-projects/reference-fluid-thermodynamic-and-transport-properties-database-refprop).

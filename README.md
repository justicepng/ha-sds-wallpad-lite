# Samsung SDS Wallpad Lite Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/default)
[![GitHub Release](https://img.shields.io/github/v/release/justicepng/ha-sds-wallpad-lite)](https://github.com/justicepng/ha-sds-wallpad-lite/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

삼성 SDS 월패드의 RS485 통신 라인(EW11 Wi-Fi 어댑터)에서 **난방 온도조절기 5개**와 **실시간 소비전력량**만 가볍고 안정적으로 Home Assistant에 연동하는 네이티브 커스텀 통합구성요소(Custom Component)입니다.

---

## 🌟 개발 배경 및 특징

기존 삼성 SDS RS485 애드온은 조명, 환기, 가스밸브, 콘센트, 현관 스위치, 인터폰, 엘리베이터 등 다양한 기능을 한꺼번에 스캔/폴링하여 소켓 환경에서 패킷 충돌 및 딜레이가 발생하기 쉽습니다.

본 컴포넌트는 엘리베이터 등 실시간 제어가 필요한 장치를 Web API로 분리한 환경에서, **오직 난방과 전력량만 100% 네이티브 비동기(asyncio) 소켓으로 직접 연동**하여 다음과 같은 장점을 제공합니다:

1. **MQTT 브로커 및 애드온 불필요**: Home Assistant가 EW11(`192.168.0.16:8899`)에 직접 소켓 연결하므로 구조가 매우 단순하고 가볍습니다.
2. **기존 엔티티 및 통계 100% 승계**:
   - `climate.sds_wallpad_sds_thermostat_1` ~ `5` 난방 엔티티 ID 완벽 호환
   - `sensor.sds_wallpad_sds_power_consumption` 엔티티 ID 및 단위(W)를 그대로 유지하므로, 기존에 연결된 **리만적분(Riemann sum, `sensor.sds_energy`)과 유틸리티 미터(일간/월간 에너지 통계)가 초기화 없이 그대로 연속 동작**합니다.
3. **네트워크 단절 시 자동 재연결(Auto-reconnect)** 내장.
4. **HACS 표준 호환 및 UI Config Flow 지원**: YAML 수정 없이 HA UI에서 바로 설정 가능.

---

## 📱 생성 엔티티 목록

| 도메인 | 엔티티 ID | 기본 이름 | 설명 |
| :--- | :--- | :--- | :--- |
| `climate` | `climate.sds_wallpad_sds_thermostat_1` | 거실 난방 | 난방 켜기/끄기, 현재/목표 온도 제어 (10~30℃) |
| `climate` | `climate.sds_wallpad_sds_thermostat_2` | 안방 난방 | 난방 켜기/끄기, 현재/목표 온도 제어 |
| `climate` | `climate.sds_wallpad_sds_thermostat_3` | 알파룸 난방 | 난방 켜기/끄기, 현재/목표 온도 제어 |
| `climate` | `climate.sds_wallpad_sds_thermostat_4` | 유진방 난방 | 난방 켜기/끄기, 현재/목표 온도 제어 |
| `climate` | `climate.sds_wallpad_sds_thermostat_5` | 상수방 난방 | 난방 켜기/끄기, 현재/목표 온도 제어 |
| `sensor` | `sensor.sds_wallpad_sds_power_consumption` | SDS월패드 전기 사용량 | 실시간 소비전력 (W, 측정치) |

---

## ⚙️ EW11 통신 설정 권장값

* **Serial Settings**:
  * Baudrate: `9600`
  * Data Bits: `8`
  * Parity: `Even`
  * Stop Bits: `1`
* **Communication Settings**:
  * Protocol: `TCP Server`
  * Port: `8899`

---

## 🚀 설치 방법

### 방법 1. HACS (추천)
1. Home Assistant의 **HACS** > **통합구성요소** 메뉴로 이동합니다.
2. 우측 상단 메뉴(점 3개) > **사용자 지정 저장소 (Custom repositories)** 선택
3. 저장소 URL에 `https://github.com/justicepng/ha-sds-wallpad-lite` 입력 후 분류는 **Integration** 선택 후 추가
4. 목록에 나타난 **Samsung SDS Wallpad Lite**를 클릭하고 **다운로드**
5. Home Assistant를 재부팅합니다.

### 방법 2. 수동 설치
1. 본 저장소의 `custom_components/sds_wallpad_lite` 디렉토리를 통째로 다운로드합니다.
2. Home Assistant의 `/config/custom_components/sds_wallpad_lite` 위치에 복사합니다.
3. Home Assistant를 재부팅합니다.

---

## 🔧 통합구성요소 설정

1. **설정** > **기기 및 서비스** > **통합구성요소 추가** 클릭
2. **Samsung SDS Wallpad Lite** 검색 후 선택
3. EW11 연결 정보 입력:
   * **EW11 IP 주소**: `192.168.0.16` (환경에 맞게 수정)
   * **EW11 포트 번호**: `8899`
   * **소비전력 자릿수 나눔값**: `2` (기본값 2 = $10^2 = 100$으로 나눔)
4. 확인을 누르면 즉시 EW11에 접속하여 5개의 난방 기기와 1개의 전력량 센서가 등록됩니다.

---

## 📄 라이선스
MIT License

# maXTouch T37 정전용량 데이터 스트리밍 — 문제 해결 기록

PIC32MZ EF Curiosity 2.0 보드에서 maXTouch T37(진단) 정전용량 raw 데이터를
UART로 PC에 스트리밍하는 기능. "데이터가 하나도 안 들어온다"에서 시작해
정상 동작까지의 원인과 해결을 정리한다.

- 보드: **PIC32MZ EF Curiosity 2.0** (MCU `PIC32MZ2048EFM144`, 144-pin)
- 펌웨어 프로젝트: `apps/legato_quickstart/firmware`
  (config: `ili9488_rgb565_mxt_mzef_cu_cpro`, 16-bit 병렬/EBI 디스플레이)
- 앱 소스: `src/app.c`, 드라이버: `.../driver/input/drv_maxtouch.c`
- 호스트 리더: `tools/t37_reader.py`

---

## 최종 동작 설정 (요약)

| 항목 | 값 |
|------|-----|
| 전송 UART | **UART6** |
| U6TX 핀 | **RPF2** (물리 핀 79) — `RPF2R = 4` |
| U6RX 핀 | **RPF13** (물리 핀 57) — `U6RXR = 9` |
| 실제 baud | **28800** (115200 아님 — 아래 4번 참고) |
| PC 포트 | `/dev/cu.usbmodemBUR...` (보드 PKoB4 디버거 가상 COM) |
| 데이터 소스 | `DRV_MAXTOUCH_T37Read()` (실제 정전용량, dummy 아님) |

실행:
```bash
python3 tools/t37_reader.py \
    --port /dev/cu.usbmodemBUR2533141202 \
    --baud 28800 --nums
```

---

## 문제 1 — usbmodem 포트로 데이터가 0바이트

### 증상
`/dev/cu.usbmodemBUR...` 포트로 리더를 돌려도 아무것도 안 들어옴(raw read 0바이트).

### 원인
- `usbmodem...` 포트는 보드의 **PKoB4 온보드 디버거 가상 COM(VCOM)** 이다.
- 초기 펌웨어는 UART6 출력(U6TX)을 **RPB3** 핀으로 PPS 매핑(`RPB3R = 7`)했다.
- RPB3는 그냥 헤더 GPIO 핀이고, 디버거 VCOM과 **물리적으로 연결돼 있지 않다.**
  → VCOM(usbmodem)으로는 영원히 데이터가 안 온다.

### 핵심 사실 (보드 스키매틱 + 데이터시트 PPS로 확인)
- 디버거 VCOM은 MCU **UART6** 에 연결됨 (스키매틱 네트 `UART6_TX`/`UART6_RX`).
- VCOM의 실제 MCU 핀:
  - **U6TX = RPF2 (RF2, 핀 79)**
  - **U6RX = RPF13 (RF13, 핀 57)**
- 헷갈리기 쉬운 함정: `RPF4`/`RPD15`는 **Xplained Pro 확장 헤더**의 UART
  (U3TX/U3RX)이지 디버거 VCOM이 아니다. (한 번 잘못 짚었던 부분)

### 해결
1. MHC에서 UART6 **Pin Settings**:
   - 핀 79 (RF2) → `U6TX`
   - 핀 57 (RF13) → `U6RX`
   - 기존 RPB3 매핑 해제
2. Generate → `plib_gpio.c` 결과:
   ```c
   U6RXR = 9;    // RPF13 -> U6RX
   RPF2R = 4;    // U6TX  -> RPF2
   ```
3. `app.c`는 그대로 `UART6_*` 사용.

> 대안: RPB3 매핑을 유지하고 **외장 3.3V USB-시리얼 어댑터**의 RX를 RPB3,
> GND를 GND에 연결해서 어댑터 포트(`/dev/cu.usbserial-*`)로 읽어도 된다.
> usbmodem(보드 USB) 하나로 끝내려면 위 RPF2/RPF13 방식이 맞다.

---

## 문제 2 — PPS 매핑 가능 여부 (왜 핀이 Pin Table에 안 보였나)

PIC32MZ는 PPS(Peripheral Pin Select)에 **그룹** 제약이 있다. 어떤 UART의
TX/RX는 같은 PPS 그룹의 핀에만 매핑된다. 그래서 엉뚱한 UART를 골라
RPF2/RPD15 등을 찾으면 Pin Table에 아예 안 나타난다.

디바이스 팩에서 직접 확인:
`~/.mchp_packs/Microchip/PIC32MZ-EF_DFP/<ver>/edc/PIC32MZ2048EFM144.PIC`
의 `<edc:VirtualPin ... ppsgroup ppsval>` 항목.

| 신호 | PPS 그룹 | 비고 |
|------|---------|------|
| U6TX | 3, 4 | RPF2(그룹4)에 매핑 가능 → `RPF2R = 4` |
| U6RX | 4 | RPF13(그룹4, ppsval 9) 매핑 가능 → `U6RXR = 9` |
| U3TX | 1 | RPF4(그룹1) — EXT 헤더용 |
| U3RX | 2 | RPD15(그룹2) — EXT 헤더용 |

교훈: **VCOM = UART6, 핀은 RPF2/RPF13.** 다른 UART/핀 조합은 안 됨.

---

## 문제 3 — 데이터는 들어오는데 "가짜"였다 (움직이는 점 @ 하나)

### 증상
파이프라인이 뚫린 뒤 히트맵에 `@` 하나가 위→아래로 쓸고 지나가기만 함.

### 원인
`app.c`의 `APP_T37_CaptureAndSend()`가 실제 센서를 안 읽고
**dummy 움직이는 점**을 생성하고 있었음.

### 해결
`drv_maxtouch.c`에 이미 있던 실제 API로 교체:
- `APP_STATE_T37_WAIT_READY`: `DRV_MAXTOUCH_IsReady(DRV_HANDLE_INVALID)`가
  true가 될 때까지 대기.
- `APP_T37_CaptureAndSend()`: dummy 제거 →
  `DRV_MAXTOUCH_T37Read(DRV_HANDLE_INVALID, APP_T37_MODE, appT37Nodes,
   APP_T37_MAX_NODES, &xSize, &ySize)` 호출, 반환된 실제 노드값/매트릭스
   크기로 프레임 구성.

참고:
- `APP_T37_MODE` 기본 = `DRV_MAXTOUCH_T37_MODE_DELTAS`
  (기준 대비 변화량 → 안 만지면 ~0, 만지면 그 자리 값 튐).
- 손 전체 baseline을 보려면 `DRV_MAXTOUCH_T37_MODE_REFS`로 변경(`app.c`).

---

## 문제 4 — baud가 115200이 아니라 28800

### 증상
115200으로 읽으면 `78 00 80...` 식으로 깨짐. 모든 표준 baud에서 깨짐.

### 원인 (펌웨어 생성코드 버그)
생성된 `UART6_SerialSetup()`이 BRG 값을 **BRGH=1 공식**으로 계산하는데,
정작 `U6MODE`의 **BRGH 비트를 켜지 않는다**(Initialize에서 `U6MODE=0x0`).
결과적으로 `U6BRG = 216` + `BRGH=0` → 실제 baud:
```
baud = PBCLK2 / (16 * (216 + 1)) = 100MHz / 3472 ≈ 28800
```

### 해결 (현재)
호스트를 **28800**으로 읽는다: `--baud 28800`.
28800에서 페이로드 `00 0a 00 0a...`(노드값 10) 정상 확인됨.

### 진짜 115200을 원하면
펌웨어에서 SerialSetup이 BRGH 비트를 세팅하도록 고치거나, MHC UART6 baud
설정을 BRGH=0 기준 BRG와 맞도록 조정. (현재는 미적용 — 28800 사용)

---

## 와이어 프로토콜

바이너리, 리틀엔디안, 스캔 1회당 1프레임:

```
오프셋  필드            바이트
  0     sync0 = 0xAA      1
  1     sync1 = 0x55      1
  2     mode              1     0x10=deltas, 0x11=refs
  3     xSize             1
  4     ySize             1
  5     nodeCount         2     uint16 = xSize*ySize
  7     payload    nodeCount*2  노드당 int16, k -> x=k//ySize, y=k%ySize
  ...   checksum          2     uint16 = payload 합 (mod 65536)
```

---

## 호스트 리더 (`t37_reader.py`) 사용법

```bash
# ASCII 히트맵 (기본)
python3 tools/t37_reader.py --port <PORT> --baud 28800

# 숫자 그리드 (행=X채널, 열=Y채널)
python3 tools/t37_reader.py --port <PORT> --baud 28800 --nums

# 타임스탬프와 함께 CSV 저장
python3 tools/t37_reader.py --port <PORT> --baud 28800 --csv capture.csv

# 저장 + 화면 숫자 동시
python3 tools/t37_reader.py --port <PORT> --baud 28800 --csv capture.csv --nums

# matplotlib 라이브 히트맵
python3 tools/t37_reader.py --port <PORT> --baud 28800 --plot

# ML용 npz
python3 tools/t37_reader.py --port <PORT> --baud 28800 --npz data.npz --label fist
```

옵션: `--label <태그>`, `--count <N>`(N프레임 후 종료), `--quiet`.

### CSV 컬럼
`t`(epoch 초, 0.1ms) | `iso`(ISO8601, **ms**) | `label` | `mode` |
`xsize` | `ysize` | `n0..nN`(노드값).

타임스탬프 주의: **호스트(PC) 수신 시각**이다(MCU 캡처 시각 아님).
~20Hz(50ms 주기) + 시리얼/USB 지터가 있어 행 간격은 정확히 50ms가 아니다.
샘플의 실제 캡처 시각이 필요하면 펌웨어가 프레임에 MCU 타임스탬프(SYS_TIME)를
실어 보내도록 확장해야 한다.

---

## 빠른 점검 순서 (다음에 또 안 될 때)

1. 포트로 raw 바이트가 들어오나? (0이면 핀/플래시/배선 문제 → 문제 1)
2. 바이트는 오는데 깨지나? → baud (`--baud 28800`) → 문제 4
3. sync `AA 55`는 잡히는데 `@` 하나만 움직이나? → dummy 코드 → 문제 3
4. PPS가 안 맞나(`plib_gpio.c`에 `RPF2R=4`, `U6RXR=9` 있는지) → 문제 1·2

---

## 문제 5 — 프레임 속도가 ~1Hz (목표: 최대한 빠르게)

### 증상
파이프라인 정상인데 프레임 속도가 ~1Hz로 너무 느림.

### 원인 (우선순위 순, 전부 MHC 생성 기본값 — 사용자/이전 작업 도입 아님)

| 원인 | 영향 |
|------|------|
| `I2C2BRG = 4992` (MHC 기본값) | ~10kHz I2C → 프레임당 ~700ms, **지배적 병목** |
| UART6 BRGH 비트 미설정 | 실제 baud 28800 (115200 요청해도) — 문제 4와 동일 근본 원인, **BRGH 마스크 자체를 세팅 안 함** |
| 노드 버퍼 1024개 (실제 매트릭스 336개) | 불필요 RAM/처리 |
| T37 페이지 6개 읽기 (live 데이터는 5페이지면 충분) | I2C 왕복 1회 낭비 |
| T37 페이지 폴링 시 매번 130B 풀리드 | 헤더만 보면 되는데 매 retry마다 전체 재독 |

### 해결
1. **`plib_i2c2_master.c`**: `I2C2BRG = 4992` → `242` (~200kHz). 400kHz(BRG=117)
   시도했으나 이 보드 풀업 특성상 버스 wedge 발생 → 200kHz로 확정. **단일 최대 기여.**
2. **`plib_uart6.c`**: `UART6_Initialize()`와 `UART6_SerialSetup()` 양쪽에
   `_U6MODE_BRGH_MASK` 세팅 추가. baud 460800으로 상향.
3. **`drv_maxtouch.c`** T37 폴링: 헤더 2바이트만 먼저 폴링 → ready 확인 후
   전체 1회 읽기 (매 retry 130B → 2B).
4. **`app.c`**:
   - `APP_T37_MAX_NODES` 1024 → 336 (실제 14×24 매트릭스)
   - `APP_T37_READ_NODES` = 320 (마지막 dead 페이지 k320~335 스킵, 6→5페이지)
   - `APP_T37_PERIOD_MS` 50 → 10 (실제 병목은 I2C라 인위적 페이싱 캡 제거)
   - **Live crop**: 14×24 → 14×8 (Y8~23 물리 미연결, 항상 0) 인플레이스 압축
     후 전송 → 프레임 681B → 233B

### 결과
~1Hz → **~17Hz**. 컨트롤러 T37 페이지당 서빙 지연(~8~12ms, 실리콘 고정)이
진짜 상한 — I2C 클럭 추가 상향, T7 acquisition 튜닝 둘 다 효과 없음 확인됨.
5페이지 × ~10ms ≈ 50ms/프레임 → ~17~20Hz가 이 방식의 실질 천장.

> ⚠️ **MHC 재생성 시 전부 복구됨** (`plib_i2c2_master.c`, `plib_uart6.c`,
> `drv_maxtouch.c`는 생성 파일). 영구 적용하려면 MHC에서 I2C2 clkSpeed=400000
> 등으로 설정해두고 재생성해야 함. `app.c`는 생성 파일 아니라 안전.

---

## 문제 6 — `_T37_WaitI2C` 무한 스핀 → 펌웨어 완전 정지

### 증상
I2C 200kHz로 올린 뒤 한참 잘 돌다가 스트림이 멈춤("돌다가 멈춤"). USB CDC
포트는 계속 열려 있지만 (`ls /dev/cu.usb*`에 보임) 바이트가 0개로 영원히 안 옴.

### 원인
`_T37_WaitI2C`가 I2C 전송 완료를 기다리는 루프에 **타임아웃이 없었음**.
버스가 가끔 wedge(PENDING 상태에서 안 빠짐)되면 이 루프가 무한 스핀 →
APP_Tasks 자체가 멈춤 → UART로 아무것도 안 나감.

### 해결
`drv_maxtouch.c`의 `_T37_WaitI2C`에 spin 카운터 기반 타임아웃 추가
(5,000,000회 ≈ 수백 ms 초과 시 `false` 반환, 한 프레임만 drop하고 다음
사이클로 복귀):
```c
uint32_t spins = 0;
do {
    ev = DRV_I2C_TransferStatusGet(th);
    if (ev == DRV_I2C_TRANSFER_EVENT_PENDING && ++spins > 5000000u)
        return false;
} while (ev == DRV_I2C_TRANSFER_EVENT_PENDING);
```

### 진단 팁 (포트는 열리는데 데이터 0일 때)
```python
import serial, time
s = serial.Serial('<PORT>', 460800, timeout=1)
time.sleep(0.3); s.reset_input_buffer()
b = s.read(256)
print(len(b), b[:16].hex())   # 0이면 보드 freeze, 펌웨어 쪽 문제
```
0바이트면 **보드 리셋(MCLR or USB 재꽂기)** 으로 임시 복구. 자주 재발하면
해당 보드의 I2C 풀업/배선 점검 필요 (200kHz도 wedge되면 더 낮춰야 함).

---

## 문제 7 — 보드 2개 동시 캡처 시 동기화 안 맞음

### 증상
두 보드를 동시에 꽂고 `--port A B`로 멀티포트 캡처하면 프레임이 안 맞아
보임.

### 원인
두 보드는 **독립적으로 free-run** — 공유 클럭/트리거가 없어 절대 동시에
캡처 안 됨. (멀티포트 모드 자체는 이미 포트별 스레드로 동작 중이라 스레드
문제 아님.)

### 해결
`t37_reader.py`에 `write_aligned_csv()` 추가. 캡처 종료 후 `*_aligned.csv`를
별도 생성:
- port0 각 프레임을 호스트 타임스탬프 `t` 기준으로 가장 가까운 port1
  프레임과 페어링 (`bisect`로 nearest-neighbor)
- tolerance = port0 프레임 주기의 중앙값(약 1 프레임) — 그보다 먼 페어는 버림
- 컬럼: `t0, t1, dt_ms, label, a0..a111(port0), b0..b111(port1)` — ML 바로 입력

측정 예 (300프레임 캡처, 실측): 260/292 페어 성공(89%), `dt_ms` 중앙값
**10.8ms**, 평균 15.3ms, 최대 57ms. 한 프레임 주기(~60ms)의 1/6 수준으로
충분히 정렬됨.

**한계**: 소프트웨어 정렬 천장은 ±한 프레임 주기 절반. 두 보드 본연의 Hz가
다를 수 있음(I2C/컨트롤러 개체차, 실측 한 쌍에서 port0 15Hz vs port1
12Hz — **USB 2.0/3.0 차이 아님**, USB는 460800bps 정도는 USB1.1로도 남는
대역폭이라 무관. 보드별 I2C/펌웨어 버전 차이가 원인). 진짜 <1ms 동시 캡처가
필요하면 공통 GPIO 트리거로 하드웨어 동기화해야 함 — 소프트웨어 영역 밖.

---

## 문제 8 — 멀티포트 캡처 중 한 보드가 freeze해도 조용히 진행됨

### 증상
듀얼 캡처 중 한 보드가 문제 6처럼 freeze되면(또는 USB가 빠지면) 다른 포트
데이터만 쌓이고 사용자는 한참 뒤 CSV를 열어봐야 알아챔 (`p0=0` 식으로
뒤늦게 발견).

### 원인
- `worker()` 스레드가 `read_frame()`에서 `serial.SerialException`을 못
  잡으면 조용히 죽음(USB 물리적 분리 시).
- 펌웨어 freeze(USB는 살아있고 바이트만 0)인 경우는 예외도 안 뜨고 그냥
  타임아웃 `None`만 반복 → `--quiet`에서는 아무 표시도 없음.

### 해결
1. `worker()`에 `serial.SerialException` 캐치 추가 → 끊기면 즉시
   `[port{i}] 연결 끊김: ...` 출력하고 전체 캡처 중단.
2. `--quiet`에서도 2초마다 헬스 체크 라인 출력:
   ```
   [10:39:12] p0=STALL!  p1=15Hz
   ```
   직전 체크 구간에서 프레임 0개면 `STALL!`, 아니면 실측 Hz 표시. 펌웨어
   freeze(포트는 열렸지만 데이터 없음)가 캡처 도중 바로 눈에 보임.
3. `run_capture_multi()`의 `finally` 블록에서 `csv_f.close()`가 두 번
   호출되던 버그도 같이 제거 (`write_aligned_csv` 호출 전후로 중복 close).

### 진단 순서 정리
1. `--quiet` 헬스 라인에서 `STALL!` 뜨는 포트 확인
2. 해당 포트 raw 바이트 직접 읽어 0인지 확인 (문제 6의 진단 스니펫)
3. 0바이트면 보드 리셋, `SerialException` 메시지 뜨면 USB 케이블/포트 점검

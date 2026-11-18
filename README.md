# ExamSentry AI

> 시험장에 몰래 들고 온 **무선 기기(초소형 카메라·AI 안경·초소형 이어폰)** 의 신호를
> 시험 시간 내내 AI로 분석해서, 시험장 밖 감독관 태블릿에 **"쉬는 시간에 ○○ 부근을 확인하세요"** 라고 알려 주는 시스템

```
 숨긴 기기 ))) 📡 ESP32 센서 4대 ──USB──▶ 💻 노트북 (AI 분석) ──Wi-Fi──▶ 📱 감독관 태블릿
             (교실 네 모서리)                ① 어디 부근?  ② 얼마나 의심?     쉬는 시간에 확인
```

- 시험 중에는 **개입하지 않습니다.** 신호를 계속 쌓아 두었다가 쉬는 시간에 확인할 곳만 알려 줍니다.
- 기기 주인이나 부정행위 여부를 판정하지 않습니다. **"확인할 곳"** 을 알려 줄 뿐입니다.
- 대회에서는 실제 교실 대신 **1:10 우드락 모형**으로 시연합니다.

### 📚 팀 문서

| 문서 | 내용 |
|---|---|
| [소개서 v3 (PDF)](docs/ExamSentry_소개서_v3.pdf) | 개요 · 준비물·예산 · 작동 원리 · 2분 시연과 일정 (4쪽) |
| [시연 구성 페이지](https://claude.ai/artifact/7EgCDSjFHBoCVimPqJjBn9) | 전체 구조, 감지 대상, 1:10 모형, 준비물 |
| [4인 숙제 페이지](https://claude.ai/artifact/1F9Pe9Ld64d7GHjcbHAwdL) | 전체 할 일, 송이·A·B·C 역할별 체크리스트 |
| [코드 지도](https://claude.ai/artifact/FLcH5mAC6e5hkHFZXu8G64) | 파일별 역할·확인 상태(돌려 봄 / 컴파일만 / 보드 와야), 공부할 주제와 사람별 순서 |

> 페이지 링크는 공유받은 사람만 열 수 있습니다. 안 열리면 송이에게 요청하세요.

---

## 🤖 Claude로 이어서 하기

이 폴더에는 Claude용 안내 파일(`CLAUDE.md`)과 팀 전용 명령어가 들어 있어서, 누가 Claude Code를 켜도 지금까지의 결정과 진행 상황을 알고 시작합니다.

```bash
git clone https://github.com/wsongi3412/smartIT.git   # 처음 한 번 (이후엔 git pull)
cd smartIT
claude                                                # Claude Code 실행
```

| 명령어 | 하는 일 |
|---|---|
| `/status` | 지금 진행 상황 요약 (최근 변경, 확인 상태, 다음 할 일) |
| `/role B` | 내 역할(송이·A·B·C)의 할 일 + 지금 바로 할 첫 단계 안내 |
| `/demo` | 감독관 태블릿 화면을 가짜 데이터로 띄워 보기 |
| `/check` | `run_all.py` 채점 돌리고 결과를 쉬운 말로 설명 |
| `/log 오늘 한 일` | 진행 기록(`docs/진행기록.md`)에 추가 |

그냥 물어봐도 됩니다. 예: "pipeline.py가 뭐 하는 건지 쉽게 설명해 줘", "B 역할인데 신호 지도 측정 절차서 초안 같이 만들자".

진행 기록은 [`docs/진행기록.md`](docs/진행기록.md) 에 날짜별로 남습니다.

---

## 📌 지금 상태 (2026-11-18)

**ESP32가 아직 없어서, 가짜 센서 데이터로 처음부터 끝까지 돌아가게 만들어 두었습니다.**
ESP32가 오면 입력만 진짜 센서로 바꾸면 됩니다. (데이터 형식이 같음)

| | 내용 |
|---|---|
| ✅ 돌려서 확인함 | AI 분석, 태블릿 화면, 가짜 데이터, 채점, 실시간 시연 리허설 |
| ⏳ ESP32 와야 확인 | ESP32 펌웨어 3개 (**컴파일은 통과**, 보드에 올려 보기만 남음), USB 수집기, 신호 지도 기록기 |
| ❌ 아직 없음 | 대시보드 보정 모드 화면, 누적 열지도 |

> ⚠️ 아래 나오는 정확도 숫자는 전부 **시뮬레이션(가짜 데이터)** 결과입니다. 코드가 맞게 도는지 확인하는 용도이고, **발표에는 모형에서 직접 잰 숫자만** 씁니다.

---

## 🚀 5분 만에 돌려 보기 (노트북만 있으면 됨)

```bash
git clone https://github.com/wsongi3412/smartIT.git
cd smartIT
pip install -r requirements.txt

python server.py
```

브라우저에서 **http://localhost:8000** 을 열면, 50분 시험이 30초로 빨리 재생됩니다.
숨긴 카메라가 `관찰 → 높음` 으로 올라가고, 끝나면 **"쉬는 시간입니다. 확인할 곳: ○○ 부근"** 이 뜹니다.

태블릿으로 보려면 노트북과 같은 Wi-Fi에 연결하고, 서버가 알려 주는 `http://<노트북 IP>:8000` 으로 접속하세요.

그 밖에 해 볼 수 있는 것:

```bash
python evaluate.py                 # 성공 기준 채점 (정확도, 오판, 몇 번 잡았나)
python evaluate.py --wall-db 2     # 알루미늄 테이프 없이 우드락 벽만이면? (복도 오판 40%!)
python evaluate.py --dead D        # 센서 D가 고장 나면?
python train_rf.py                 # 의심도 AI(랜덤포레스트) 학습 → data/rf.pkl
python server.py --model data/rf.pkl   # 규칙 대신 AI 모델로 판정
python run_all.py                  # ⭐ 전체 한 번에: 채점 + AI 학습 + 혼동 행렬 그림 + 보고서
```

`run_all.py` 결과는 `results/<날짜_시각>/` 에 생깁니다: `report.md`(목표 대비 ✅/❌), `confusion.png`(혼동 행렬), `signals.csv`(신호별 판정), `rf.pkl`(AI 모델).

실시간 시연 리허설 (가짜 ESP32 4대):

```bash
python fake_live.py data/live.csv                     # 터미널 1: 가짜 센서
python server.py --live data/live.csv --scale 40      # 터미널 2: 서버
# 태블릿 화면 버튼: [기준선] → [시험 시작] → (자동) 쉬는 시간
```

---

## 🧠 AI는 두 단계로 판단합니다

### 1단계 · 어디 부근인가? (2초마다)

1. 센서 4대(A·B·C·D)가 받은 신호 세기를 2초씩 묶습니다. 예: `[-52, -71, -76, -81]`
2. 미리 만든 **신호 지도**(구역마다 기기를 두고 기록한 세기)와 비교합니다.
3. 가장 비슷한 기록 5개(k-NN, k=5) 중 3개 이상이 같은 구역이면 그 구역으로 판정합니다. 아니면 "판단 보류"로 둡니다.

> 비유: "지금 들리는 소리 크기가 예전에 *뒤오른쪽* 에서 들렸던 크기랑 제일 비슷하네."

### 2단계 · 얼마나 의심스러운가? (시험 내내 누적)

신호마다 아래를 쌓아서 **낮음 / 관찰 / 높음** 을 매깁니다.

| 보는 것 | 왜 |
|---|---|
| 교실 안에 있었던 누적 시간 | 숨긴 기기는 오래 있음 (20분 이상이면 높음) |
| 교실 안 비율 | 복도를 지나가는 사람은 대부분 교실 밖 |
| 시험 전에도 있었나 (기준선) | 원래 있던 장비·건물 Wi-Fi는 제외 |
| 전송량, 구역 변화, 다시 나타남 | 카메라는 데이터를 많이 보냄 등 |

- 처음엔 **규칙**(20분 이상 → 높음)으로 시작하고, 데이터가 모이면 **랜덤포레스트**와 비교합니다.
- AI 안경처럼 **주소(MAC)를 계속 바꾸는 기기**도 "같은 자리에서 비슷한 세기" 면 같은 기기로 이어 붙입니다.
- 기기 이름이 아니라 **행동**만 보고 판단하기 때문에, 비싼 실제 기기 대신 싼 대역 기기로 학습해도 됩니다.

---

## 📁 파일 설명

```
smartIT/
├── config.py          ⚙️  모든 설정 (모형 크기, 센서 위치, 기준값). 숫자 바꿀 땐 여기만!
├── pipeline.py        🧠  AI 본체: 2초 묶기 → 위치 판정 → 신호 이어 붙이기 → 의심도
├── train_rf.py        🧠  의심도 AI(랜덤포레스트) 학습: 1일차 학습 / 2일차 시험
├── run_all.py         ⭐  한 번에 돌리기: 위치 채점 → 시험 채점 → AI 학습 → 보고서·그림
├── server.py          📱  태블릿 화면 서버 (리플레이 · 실시간 · 압축 시연, 시험 끝나면 기록 자동 저장)
├── dashboard.html     📱  태블릿 화면 (배치도, 신호 목록, 쉬는 시간 배너, 센서 상태)
├── serial_reader.py   🔌  [ESP32용] 센서 4대 USB → CSV 저장 (주소는 해시로)
├── stage_log.py       🔌  [ESP32용] 신호 지도 만들 때 "지금 어느 구역" 기록
├── sim.py             🧪  가짜 센서 데이터 만들기 (숨긴 기기, 복도 통행 등)
├── fake_live.py       🧪  가짜 ESP32 4대 (실시간 리허설용)
├── evaluate.py        🧪  성공 기준 채점
├── whitelist.txt          팀 노트북·핫스팟·태블릿 주소 (제외할 기기)
├── requirements.txt
└── firmware/
    ├── esp32_sensor/      📡  센서 4대에 올릴 프로그램 (1초 블루투스 ↔ 1초 Wi-Fi)
    ├── esp32_beacon/      📡  비콘(여분 ESP32): 신호 지도 측정 · 복도 통행 역할
    └── esp32cam_glasses/  🕶  AI 안경 대역(ESP32-CAM): BLE 계속 + 30초마다 사진 Wi-Fi 전송 + 10분마다 MAC 교체
```

### 역할별로 먼저 볼 파일

| 역할 | 먼저 볼 것 |
|---|---|
| 1 하드웨어 | `firmware/` 폴더 → ESP32 오면 1대에 먼저 올려 보기 |
| 2 수집·데이터 | `serial_reader.py`, `stage_log.py`, 아래 "데이터 형식" |
| 3 AI | `run_all.py` ⭐, `pipeline.py`, `config.py`, `evaluate.py`, `train_rf.py` |
| 4 대시보드·발표 | `server.py`, `dashboard.html`, 아래 "2분 시연 타이밍" |

---

## 🔍 가짜 데이터로 실험해서 알아낸 것

| 조건 | 복도를 교실 안으로 잘못 봄 | 숨긴 기기 '높음' (카메라·이어폰·AI 안경) | 잘못된 경보 |
|---|---|---|---|
| 우드락 벽만 | **40%** 😱 | 10 · 7 · 10 /10 | 0 |
| **알루미늄 테이프 벽** | **8%** | 10 · 9 · 10 /10 | 0 |
| 알루미늄 + 센서 D 고장 | 6% | 10 · 10 · 10 /10 | 0 |

1. **알루미늄 테이프 벽은 필수.** 센서가 벽 위에 있으면 벽 바로 안쪽 자리와 바로 바깥 복도가 거의 똑같이 보입니다. 진짜 교실은 콘크리트 벽이 막아 주지만 우드락은 못 막습니다. (발표 때 "벽을 흉내 냈다"고 밝히기)
2. **센서는 4대.** 4대 79% / 3대 72~74% / 2대 62%. 그리고 4대는 1대가 빠져도 남은 3대로 계속 판정하지만, 3대는 1대만 빠져도 멈춥니다.
3. 신호 지도를 만들 때 **비콘과 ESP32-CAM 둘 다** 로 기록해야 합니다. (기기마다 신호 세기가 달라서)

---

## 🛠 ESP32가 오면 할 일 (순서대로)

1. Arduino IDE → 보드 매니저에서 **esp32 (Espressif) 3.3.x** 설치 → `firmware/esp32_sensor` 를 **1대에만** 올려서 시리얼 모니터에 줄이 찍히는지 확인
   - ⚠️ 센서 펌웨어는 **툴 → Partition Scheme → "Huge APP (3MB No OTA/1MB SPIFFS)"** 로 바꿔야 들어갑니다 (기본 설정이면 '용량 초과' 오류)
2. 코드 맨 위 `SENSOR_ID` 를 A/B/C/D로 바꿔 4대에 올리기. 핫스팟 채널을 고정하고 `WIFI_CH` 를 맞추기
3. `pip install pyserial` → `python serial_reader.py data/live.csv` → 4대 모두 데이터가 들어오는지
4. 여분 ESP32에 `firmware/esp32_beacon` → 시리얼 모니터에서 비콘 주소 확인
5. **에어팟·버즈 1분 확인**: 케이스 열고 음악 재생 → 새 주소가 계속 잡히는지 (안 보이면 비콘으로 대체)
6. **신호 지도 1일차**: `python stage_log.py data/calib_day1.csv --id <비콘 주소>` → 구역마다 여러 자리, 자리당 6초 이상
7. **다른 날 2일차** 측정 → `python evaluate.py --calib-train data/calib_day1.csv --calib-test data/calib_day2.csv` → **진짜 수치**
8. 실시간: `python server.py --live data/live.csv --calib data/calib_day1.csv --scale 40`
9. **시험 연출 기록**: 실시간 모드로 시험을 끝낼 때마다 `data/exams/exam_시각.csv` 가 자동 저장됩니다. 같이 생기는 `_truth.csv` 의 level 칸에 정답(높음/관찰/낮음)을 채우고, 1일차·2일차 폴더로 나눠 둡니다.
10. **한 번에 채점**:
    ```bash
    python run_all.py --calib1 data/calib_day1.csv --calib2 data/calib_day2.csv \
                      --exams1 data/exams/day1 --exams2 data/exams/day2
    ```
    → `results/.../report.md` 의 숫자가 **발표용 실측 수치**입니다.

---

## 🔧 펌웨어 컴파일 (보드 없어도 됨)

| 펌웨어 | 보드 선택 | 설정 | 용량 |
|---|---|---|---|
| `esp32_sensor` | ESP32 Dev Module | **Partition Scheme: Huge APP** | 52% |
| `esp32_beacon` | ESP32 Dev Module | 기본 | 83% |
| `esp32cam_glasses` | AI Thinker ESP32-CAM | 기본 | 56% |

명령어로 한 번에 확인하려면 (`brew install arduino-cli` 후):
```bash
arduino-cli config set board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index && arduino-cli core install esp32:esp32
arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=huge_app firmware/esp32_sensor
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/esp32_beacon
arduino-cli compile --fqbn esp32:esp32:esp32cam firmware/esp32cam_glasses
```

---

## 🕶 AI 안경 대역 펌웨어 (`firmware/esp32cam_glasses`)

진짜 AI 안경은 비싸서, 같은 방식으로 신호를 내는 ESP32-CAM으로 대신합니다.

| 진짜 AI 안경 | 대역 펌웨어 |
|---|---|
| 휴대폰과 블루투스 연결 유지 | BLE 광고를 100ms마다 계속 보냄 |
| 찍은 사진을 Wi-Fi로 올림 | 30초마다 사진을 찍어 3초 동안 Wi-Fi로 몰아 보냄 |
| 주소(MAC)를 주기적으로 바꿈 | 10분마다 재부팅하며 새 무작위 MAC |

- 업로드 전에 코드 맨 위 `WIFI_SSID`, `WIFI_PASS` 를 시연 핫스팟으로 바꾸세요.
- 시리얼 모니터(115200)에 현재 주소가 찍힙니다. 주소가 바뀔 때마다 찍히니, 시험 연출 정답(`_truth.csv`)에 모두 적어 주세요.
- 숫자(30초, 10분)는 위쪽 `BURST_EVERY_S`, `ROTATE_MIN` 에서 바꿀 수 있습니다. `ROTATE_MIN 0` 이면 주소를 안 바꿉니다.

---

## 🎬 2분 시연 타이밍 (`--scale 40`: 실제 1초 = 시험 40초)

| 시각 | 할 일 | 태블릿 |
|---|---|---|
| 발표 전 | **[기준선]** 누르기. 이때 대역 기기는 **반드시 꺼 두기** | 기준선 |
| 0:15 | **[시험 시작]**, 교수님께 태블릿 드리기 | 시험 중 |
| 0:20 | 다른 교수님이 ESP32-CAM 켜서 모형 책상에 숨김 | 곧 '관찰' |
| 0:40 | 팀원이 비콘 들고 복도 지나가기 | 복도 '낮음' |
| ~1:00 | 숨긴 기기 누적 20분 도달 | **'높음'** |
| 1:30 | 50분 → 자동 쉬는 시간 | "확인할 곳: ○○ 부근" → 교수님이 찾기 |

> ⚠️ 기준선 기록할 때 켜져 있던 기기는 "원래 있던 신호"로 빠집니다. 대역 기기를 미리 켜 두면 끝까지 '높음'이 안 뜹니다!

---

## 📄 데이터 형식

ESP32가 보내는 한 줄 (1초 동안 같은 기기 패킷을 묶음):
```
A,BLE,aa:bb:cc:dd:ee:ff,-58,A,3      센서, 종류, 주소, 세기(dBm), 프레임, 패킷 수
B,WIFI,3c:71:bf:12:a0:4e,-61,D,42    프레임: A=블루투스 광고, D=Wi-Fi 데이터, M=Wi-Fi 관리
```
노트북에 저장되는 CSV (`serial_reader.py` / `sim.py` 공통):
```
t,sensor,kind,id,rssi,frame,n
1763470000.125,A,BLE,3f9a0c11b2,-58,A,3     t=시각(초), id=주소를 해시로 바꾼 값
```

## 🔒 개인정보

- 기기 주소(MAC)는 저장하기 전에 해시로 바꿉니다. 패킷 내용은 읽지도 저장하지도 않습니다.
- 팀원 개인 기기(에어팟·워치)는 학습 데이터에 넣지 않고 시험·시연에만 씁니다.
- `data/` 폴더의 CSV는 깃에 올리지 않습니다 (`.gitignore`). 가짜 데이터는 `python sim.py exam data/sample_exam.csv` 로 언제든 다시 만들 수 있습니다.

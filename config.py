"""ExamSentry 공통 설정 — 1:10 우드락 모형 기준 (길이 단위: mm, 시간 단위: 초).

좌표: 칠판 쪽 벽이 y=0, 뒤쪽 벽이 y=ROOM_D, 왼쪽 벽 x=0, 오른쪽 벽 x=ROOM_W.
복도는 오른쪽 벽 바깥(x > ROOM_W). (11-23: 실제 시험장은 대부분 복도가 오른쪽이라 뒤쪽에서 옮김)
센서: A 앞왼쪽, B 앞오른쪽, C 뒤왼쪽, D 뒤오른쪽 모서리 기둥.
"""
import hashlib

# ---- 모형 크기 ----
ROOM_W, ROOM_D = 900, 600      # 실제 9m x 6m 의 1/10
HALL_D = 150                   # 오른쪽 벽 밖 복도 띠의 폭
SENSOR_H = 150                 # 센서 기둥 높이
DEVICE_H = 40                  # 책상 위 기기 높이

SENSORS = {"A": (0, 0), "B": (ROOM_W, 0), "C": (0, ROOM_D), "D": (ROOM_W, ROOM_D)}
SENSOR_IDS = list(SENSORS)

INSIDE = ["앞왼쪽", "앞오른쪽", "뒤왼쪽", "뒤오른쪽"]
CENTER = "가운데"              # 판정상 '보류'로 취급
HALL = "복도"
ALL_ZONES = INSIDE + [CENTER, HALL]
HOLD = "보류"


def zone_of(x, y):
    """좌표 → 정답 구역 (시뮬레이션·연출 기록용)."""
    if x > ROOM_W:
        return HALL
    cx, cy = ROOM_W / 2, ROOM_D / 2
    if ((x - cx) / (ROOM_W * 0.14)) ** 2 + ((y - cy) / (ROOM_D * 0.14)) ** 2 <= 1:
        return CENTER
    return ("앞" if y < cy else "뒤") + ("왼쪽" if x < cx else "오른쪽")


# ---- 1단계: 위치 판정 ----
WINDOW_S = 2        # 2초 창
MISSING = -100      # 안 잡힌 센서 채움값
MIN_SENSORS = 3     # 3대 미만이면 창 버림
K = 5               # k-NN 이웃 수
MIN_VOTES = 3       # 5표 중 3표 이상이어야 확정
SMOOTH = 3          # 최근 3창 다수결
USE_ABS = True      # 정규화 벡터에 "가장 센 값"도 붙임 → 벽 감쇠 정보가 살아남음
ABS_WEIGHT = 1.0    # 2026-11-19 실험(docs/실험_기준값.md): 0.5→1.0 으로 복도 오판 8%→5%. 0이면 42%

# ---- 2단계: 의심도 ----
EXAM_MIN = 50
HIGH_MIN = 15       # 교실 안 누적 15분 이상 → 높음 (11-19 실험: 20→15, 잘못된 경보 0 유지, 높음 6분 빨라짐)
WATCH_MIN = 3       # 3분 이상 → 관찰
INSIDE_RATIO = 0.5  # 교실 안 비율이 이보다 낮으면 '교실 밖'
WALL_RATIO = 0.25   # 11-22 어려운 경우: 교실 안 비율 0.25~0.5 + 오래 머묾 → "관찰 (벽 근처)". 복도에 서 있는 사람은 0.0
WALL_MIN = 15       # 벽 근처로 볼 최소 누적 분 (HIGH_MIN과 같게)
REAPPEAR_GAP = 60   # 60초 넘게 끊겼다 다시 나오면 '재등장'
MERGE_GAP = 20      # MAC이 바뀐 신호를 이어 붙이는 최대 공백(초)
MERGE_DIST = 6.0    # 이어 붙일 때 허용하는 지문 거리(dB, RMS)
PROB_WATCH, PROB_HIGH = 0.4, 0.8   # RF 확률 → 단계

# ---- 개인정보: MAC 해시 ----
SALT = "examsentry-demo"           # 대회 당일엔 바꿔서 쓰기


def hash_id(raw):
    return hashlib.sha256((SALT + raw.lower()).encode()).hexdigest()[:10]

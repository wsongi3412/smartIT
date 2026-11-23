"""가짜 센서 데이터 생성기 — ESP32가 오기 전, 파이프라인 전체를 돌려 보기 위한 것.

실제 센서 출력과 같은 CSV 형식을 만든다:
    t,sensor,kind,id,rssi,frame,n
    t      : 초 (시험 시작 = 0, 기준선은 음수)
    frame  : A(BLE 광고) / D(Wi-Fi 데이터) / M(Wi-Fi 관리)
    n      : 이 줄이 묶은 패킷 수 (시뮬레이션은 1)

주의: 실제 RSSI는 이것보다 훨씬 지저분하다(반사, 사람 몸, 안테나 방향).
시뮬레이션 결과는 '코드가 맞게 돈다'는 확인이지 정확도 약속이 아니다.

사용 예:
    python sim.py calib  data/calib_day1.csv  --seed 1
    python sim.py exam   data/exam_day2.csv   --seed 2
"""
import argparse
import csv
import numpy as np
from config import (ROOM_W, ROOM_D, HALL_D, SENSOR_H, DEVICE_H, SENSORS, SENSOR_IDS,
                    ALL_ZONES, INSIDE, HALL, zone_of)

TX_10CM = {"BLE": -48.0, "WIFI": -42.0}   # 10cm에서 세기 (가정)
PATH_N = 2.2
NOISE = 3.5
DROP = 0.25
FLOOR = -95.0
WALL_DB = 10.0         # 알루미늄 테이프 벽 가정. 우드락만이면 2 정도 (--wall-db 2 로 비교)


def listening(sensor, kind, t):
    """센서는 1초씩 BLE ↔ Wi-Fi를 번갈아 듣는다. 센서마다 위상이 다르다."""
    phase = SENSOR_IDS.index(sensor) % 2
    ble_slot = (int(np.floor(t)) + phase) % 2 == 0
    return ble_slot if kind == "BLE" else not ble_slot


def rssi_at(pos, sensor, kind, rng, wall_db):
    sx, sy = SENSORS[sensor]
    d = np.sqrt((pos[0] - sx) ** 2 + (pos[1] - sy) ** 2 + (SENSOR_H - DEVICE_H) ** 2)
    v = TX_10CM[kind] - 10 * PATH_N * np.log10(max(d, 30) / 100) + rng.normal(0, NOISE)
    if pos[0] > ROOM_W:          # 복도(오른쪽 벽 밖)에서 오는 신호는 벽을 지나며 약해짐
        v -= wall_db
    return v


def emit(dev, t0, t1, rng, rows, wall_db):
    """dev: dict(id, kind, rate, pos(t)->(x,y), data_ratio)"""
    n = rng.poisson(dev["rate"] * (t1 - t0))
    for t in np.sort(rng.uniform(t0, t1, n)):
        pos = dev["pos"](t)
        frame = "A" if dev["kind"] == "BLE" else ("D" if rng.random() < dev.get("data_ratio", 0) else "M")
        for s in SENSOR_IDS:
            if not listening(s, dev["kind"], t) or rng.random() < DROP:
                continue
            v = rssi_at(pos, s, dev["kind"], rng, wall_db)
            if v >= FLOOR:
                rows.append((round(float(t), 3), s, dev["kind"], dev["id"], int(round(v)), frame, 1))


def rand_point(zone, rng):
    while True:
        x = rng.uniform(20, ROOM_W + HALL_D - 20)
        y = rng.uniform(20, ROOM_D - 20)
        if zone_of(x, y) == zone:
            return (x, y)


def rand_mac(rng):
    return "".join(f"{b:02x}" for b in rng.integers(0, 256, 6))


# ---------------- 보정(지문) 데이터 ----------------
def make_calib(seed, points_per_zone=25, hold_s=6, wall_db=WALL_DB):
    """각 구역 여러 지점에 기기를 hold_s 초씩 둔다 → raw rows + 연출 기록(labels)."""
    rng = np.random.default_rng(seed)
    rows, labels, t = [], [], 0.0
    for zone in ALL_ZONES:
        for _ in range(points_per_zone):
            for kind in ("BLE", "WIFI"):
                p = rand_point(zone, rng)
                dev = {"id": f"cal-{kind.lower()}", "kind": kind, "rate": 6 if kind == "BLE" else 10,
                       "pos": lambda _t, p=p: p, "data_ratio": 0.8}
                emit(dev, t, t + hold_s, rng, rows, wall_db)
                labels.append((t, t + hold_s, dev["id"], zone))
                t += hold_s + 1
    return rows, labels


# ---------------- 시험 시나리오 ----------------
def make_exam(seed, exam_min=50, baseline_s=120, wall_db=WALL_DB, variant=None):
    """시험 1회분. 반환: rows, truth(신호 id → 정답 등급·설명)

    등장 신호:
      - 시험 전부터 있는 것(기준선): 감독관 태블릿, 노트북 핫스팟, 건물 AP
      - 숨긴 기기 1개: Wi-Fi 카메라 / BLE 이어폰 / MAC 바꾸는 AI 안경 중 하나
      - 짧게 켜졌다 꺼진 기기(관찰 대상)
      - 복도 통행 휴대폰 여러 명(지날 때마다 MAC이 바뀜)
      - 복도에 오래 서 있는 사람 1명(어려운 경우: 높음이 뜨면 안 됨)
    """
    rng = np.random.default_rng(seed)
    end = exam_min * 60
    rows, truth = [], {}
    variant = variant or rng.choice(["cam", "ear", "glasses"])

    def add(dev, t0, t1, level, note):
        emit(dev, t0, t1, rng, rows, wall_db)
        truth.setdefault(dev["id"], (level, note))

    # 기준선 신호 (시험 전부터 끝까지)
    hall_spot = (ROOM_W + HALL_D * 0.6, ROOM_D * 0.7)
    add({"id": "tablet", "kind": "WIFI", "rate": 3, "pos": lambda t: hall_spot, "data_ratio": 0.7},
        -baseline_s, end, "낮음", "감독관 태블릿(기준선)")
    add({"id": "hotspot", "kind": "WIFI", "rate": 10, "pos": lambda t: (ROOM_W + HALL_D * 0.5, ROOM_D * 0.3),
         "data_ratio": 0.1}, -baseline_s, end, "낮음", "핫스팟(기준선)")
    add({"id": "bldg-ap", "kind": "WIFI", "rate": 10, "pos": lambda t: (ROOM_W * 0.5, -ROOM_D * 0.6),
         "data_ratio": 0.0}, -baseline_s, end, "낮음", "건물 AP(기준선)")

    # 숨긴 기기
    zone = rng.choice(INSIDE)
    p = rand_point(zone, rng)
    start = rng.uniform(2, 15) * 60
    if variant == "cam":
        add({"id": rand_mac(rng), "kind": "WIFI", "rate": 8, "pos": lambda t: p, "data_ratio": 0.9},
            start, end, "높음", f"숨긴 Wi-Fi 카메라 @{zone}")
    elif variant == "ear":
        add({"id": rand_mac(rng), "kind": "BLE", "rate": 2, "pos": lambda t: p}, start, end,
            "높음", f"숨긴 BLE 이어폰 @{zone}")
    else:  # AI 안경: 8~15분마다 MAC 교체, 머리 움직임으로 위치가 조금 흔들림
        t = start
        while t < end:
            t2 = min(end, t + rng.uniform(8, 15) * 60)
            jitter = rng.normal(0, 25, 2)
            add({"id": rand_mac(rng), "kind": "BLE", "rate": 3,
                 "pos": lambda _t, q=(p[0] + jitter[0], p[1] + jitter[1]): q}, t, t2,
                "높음", f"AI 안경(MAC 교체) @{zone}")
            t = t2 + rng.uniform(0.5, 3)

    # 짧게 켜졌다 꺼진 기기 → 관찰
    z2 = rng.choice(INSIDE)
    p2 = rand_point(z2, rng)
    s2 = rng.uniform(20, 40) * 60
    add({"id": rand_mac(rng), "kind": "BLE", "rate": 2, "pos": lambda t: p2}, s2, s2 + rng.uniform(3.5, 6) * 60,
        "관찰", f"짧게 켜진 BLE @{z2}")

    # 복도 통행: 10~25초에 걸쳐 복도를 지나감, 매번 새 MAC
    for _ in range(rng.integers(6, 12)):
        t0 = rng.uniform(-baseline_s, end - 30)
        dur = rng.uniform(10, 25)
        x = ROOM_W + rng.uniform(40, HALL_D - 20)          # 오른쪽 복도를 앞↔뒤로 지나감
        y0, y1 = (-100, ROOM_D + 100) if rng.random() < 0.5 else (ROOM_D + 100, -100)
        add({"id": rand_mac(rng), "kind": "BLE", "rate": 4,
             "pos": lambda t, t0=t0, dur=dur, x=x, y0=y0, y1=y1: (x, y0 + (y1 - y0) * (t - t0) / dur)},
            t0, t0 + dur, "낮음", "복도 통행")

    # 복도에 오래 서 있는 사람 (벽 바로 밖)
    t0 = rng.uniform(5, 20) * 60
    stand = (ROOM_W + rng.uniform(40, 90), rng.uniform(100, ROOM_D - 100))
    add({"id": rand_mac(rng), "kind": "BLE", "rate": 3, "pos": lambda t: stand}, t0, t0 + rng.uniform(20, 28) * 60,
        "낮음", "복도에 오래 서 있음")

    rows.sort(key=lambda r: r[0])
    return rows, truth, variant


# ---------------- 어려운 경우 ----------------
HARD_CASES = {
    "wall":   "복도 쪽(오른쪽) 벽 바로 앞 자리에 숨긴 BLE 이어폰 (복도와 헷갈림)",
    "center": "한가운데 자리에 숨긴 Wi-Fi 카메라 (네 센서 거리가 비슷)",
    "two":    "숨긴 기기 2개 동시 (이어폰 + 카메라, 다른 자리)",
    "hall":   "벽 바로 밖 복도에 시험 내내 서 있는 사람 (높음이 뜨면 안 됨)",
}


def make_hard(seed, case, exam_min=50, baseline_s=120, wall_db=WALL_DB):
    """어려운 경우 1회분. 기준선 신호 + 복도 통행은 make_exam과 같고, case에 따라 주인공만 다르다."""
    rng = np.random.default_rng(seed)
    end = exam_min * 60
    rows, truth = [], {}

    def add(dev, t0, t1, level, note):
        emit(dev, t0, t1, rng, rows, wall_db)
        truth.setdefault(dev["id"], (level, note))

    add({"id": "tablet", "kind": "WIFI", "rate": 3, "pos": lambda t: (ROOM_W + HALL_D * 0.6, ROOM_D * 0.7),
         "data_ratio": 0.7}, -baseline_s, end, "낮음", "감독관 태블릿(기준선)")
    for _ in range(rng.integers(6, 12)):
        t0 = rng.uniform(-baseline_s, end - 30)
        dur = rng.uniform(10, 25)
        x = ROOM_W + rng.uniform(40, HALL_D - 20)          # 오른쪽 복도를 앞↔뒤로 지나감
        y0, y1 = (-100, ROOM_D + 100) if rng.random() < 0.5 else (ROOM_D + 100, -100)
        add({"id": rand_mac(rng), "kind": "BLE", "rate": 4,
             "pos": lambda t, t0=t0, dur=dur, x=x, y0=y0, y1=y1: (x, y0 + (y1 - y0) * (t - t0) / dur)},
            t0, t0 + dur, "낮음", "복도 통행")

    start = rng.uniform(2, 10) * 60
    if case == "wall":
        p = (ROOM_W - rng.uniform(15, 60), rng.uniform(100, ROOM_D - 100))   # 오른쪽 벽에서 1.5~6cm(실제 15~60cm)
        add({"id": rand_mac(rng), "kind": "BLE", "rate": 2, "pos": lambda t: p}, start, end,
            "높음", f"복도 쪽 벽 앞 BLE 이어폰 @{zone_of(*p)}")
    elif case == "center":
        p = (ROOM_W / 2 + rng.normal(0, 25), ROOM_D / 2 + rng.normal(0, 20))
        add({"id": rand_mac(rng), "kind": "WIFI", "rate": 8, "pos": lambda t: p, "data_ratio": 0.9},
            start, end, "높음", "가운데 Wi-Fi 카메라")
    elif case == "two":
        z1, z2 = rng.choice(INSIDE, 2, replace=False)
        p1, p2 = rand_point(z1, rng), rand_point(z2, rng)
        add({"id": rand_mac(rng), "kind": "BLE", "rate": 2, "pos": lambda t: p1}, start, end,
            "높음", f"BLE 이어폰 @{z1}")
        add({"id": rand_mac(rng), "kind": "WIFI", "rate": 8, "pos": lambda t: p2, "data_ratio": 0.9},
            start + rng.uniform(0, 5) * 60, end, "높음", f"Wi-Fi 카메라 @{z2}")
    elif case == "hall":
        stand = (ROOM_W + rng.uniform(15, 60), rng.uniform(100, ROOM_D - 100))  # 벽 바로 밖
        add({"id": rand_mac(rng), "kind": "BLE", "rate": 3, "pos": lambda t: stand}, start, end,
            "낮음", "벽 바로 밖 복도에 시험 내내")
    else:
        raise ValueError(case)
    rows.sort(key=lambda r: r[0])
    return rows, truth


def save_rows(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "sensor", "kind", "id", "rssi", "frame", "n"])
        w.writerows(rows)


def save_labels(path, labels):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start", "end", "id", "zone"])
        w.writerows(labels)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["calib", "exam"])
    ap.add_argument("out")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--wall-db", type=float, default=WALL_DB)
    ap.add_argument("--variant", choices=["cam", "ear", "glasses"])
    a = ap.parse_args()
    if a.what == "calib":
        rows, labels = make_calib(a.seed, wall_db=a.wall_db)
        save_rows(a.out, rows)
        save_labels(a.out.replace(".csv", "_labels.csv"), labels)
        print(f"{len(rows)} rows, {len(labels)} staged points → {a.out}")
    else:
        rows, truth, v = make_exam(a.seed, wall_db=a.wall_db, variant=a.variant)
        save_rows(a.out, rows)
        with open(a.out.replace(".csv", "_truth.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "level", "note"])
            w.writerows((k, *v) for k, v in truth.items())
        print(f"{len(rows)} rows ({v}) → {a.out}")

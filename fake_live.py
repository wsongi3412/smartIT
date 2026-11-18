"""가짜 ESP32 4대 — serial_reader.py 대신 실시간으로 data/live.csv 에 줄을 써 준다.
실시간 모드(server.py --live)와 태블릿 버튼, 압축 시연(--scale)을 장비 없이 리허설하는 용도.

    python fake_live.py data/live.csv            # 2분 시연 시나리오
    python server.py --live data/live.csv --scale 40

시나리오 (실제 초):  0~ 기준선 기기들 / 20s 교수님이 ESP32-CAM 숨김(뒤오른쪽) / 40~55s 복도 통행
"""
import argparse
import os
import time
import numpy as np

import sim
from config import ROOM_W, ROOM_D, HALL_D, hash_id


def scenario(rng, total):
    rows = []
    hall = (ROOM_W * 0.7, ROOM_D + HALL_D * 0.6)
    devs = [
        ({"id": "tablet-mac", "kind": "WIFI", "rate": 3, "pos": lambda t: hall, "data_ratio": 0.7}, 0, total),
        ({"id": "hotspot-mac", "kind": "WIFI", "rate": 10, "pos": lambda t: (ROOM_W * 0.3, ROOM_D + 90),
          "data_ratio": 0.1}, 0, total),
        ({"id": "esp32cam-hidden", "kind": "WIFI", "rate": 8, "pos": lambda t: (720, 480), "data_ratio": 0.9},
         20, total),
        ({"id": "hall-walker", "kind": "BLE", "rate": 4,
          "pos": lambda t: (-100 + (ROOM_W + 200) * (t - 40) / 15, ROOM_D + 90)}, 40, 55),
    ]
    for d, a, b in devs:
        sim.emit(d, a, b, rng, rows, sim.WALL_DB)
    rows.sort(key=lambda r: r[0])
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--seconds", type=float, default=130)
    a = ap.parse_args()
    rows = scenario(np.random.default_rng(0), a.seconds)
    new = not os.path.exists(a.out)
    f = open(a.out, "a", buffering=1)
    if new:
        f.write("t,sensor,kind,id,rssi,frame,n\n")
    t0 = time.time()
    print(f"가짜 센서 시작 → {a.out}  ({len(rows)}줄, {a.seconds:.0f}초)")
    for t, s, k, i, v, fr, n in rows:
        wait = t0 + t - time.time()
        if wait > 0:
            time.sleep(wait)
        f.write(f"{t0 + t:.3f},{s},{k},{hash_id(i)},{v},{fr},{n}\n")
    print("끝")

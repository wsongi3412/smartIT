"""가짜 ESP32 4대 — serial_reader.py 대신 실시간으로 data/live.csv 에 줄을 써 준다.
실시간 모드(server.py --live)와 태블릿 버튼, 압축 시연(--scale)을 장비 없이 리허설하는 용도.

    python fake_live.py data/live.csv            # 2분 시연 시나리오
    python fake_live.py data/live.csv --calib-demo   # 보정 연습: 비콘이 10초마다 다음 구역으로 이동
    python server.py --live data/live.csv --scale 40

시나리오: 처음부터 원래 있던 기기들(태블릿·핫스팟)이 켜져 있고,
태블릿에서 [② 시험 시작]을 누르면 그 순간부터  +5초 ESP32-CAM 숨김(뒤오른쪽) / +25~40초 복도 통행.
(서버 화면 상태를 1초마다 확인. 서버가 없으면 --auto-start 초 뒤 시작한 걸로 침)
"""
import json
import urllib.request
import argparse
import os
import time
import numpy as np

import sim
from config import ROOM_W, ROOM_D, HALL_D, hash_id, seat_xy


CALIB_SPOTS = [("앞왼쪽", seat_xy(2, 2)), ("앞오른쪽", seat_xy(2, 4)), ("뒤왼쪽", seat_xy(4, 2)),
               ("뒤오른쪽", seat_xy(4, 4)), ("가운데", seat_xy(3, 3)), ("복도", (990, 300))]


def calib_demo(rng, total, hold=10):
    """보정 탭 연습용: 'calib-beacon' 이 hold초마다 다음 구역으로 옮겨진다 (옮기는 1초는 신호 끊김)."""
    rows = []
    hall = (ROOM_W + HALL_D * 0.6, ROOM_D * 0.7)
    sim.emit({"id": "tablet-mac", "kind": "WIFI", "rate": 3, "pos": lambda t: hall, "data_ratio": 0.7}, 0, total, rng, rows, sim.WALL_DB)
    t, k = 0.0, 0
    while t < total:
        zone, p = CALIB_SPOTS[k % len(CALIB_SPOTS)]
        sim.emit({"id": "calib-beacon", "kind": "BLE", "rate": 6, "pos": lambda _t, p=p: p}, t, min(total, t + hold - 1), rng, rows, sim.WALL_DB)
        print(f"  {t:5.0f}s~ 비콘 → {zone}")
        t += hold
        k += 1
    rows.sort(key=lambda r: r[0])
    return rows


def scenario(rng, total):   # (예전 고정 시간표, 참고용)
    rows = []
    hall = (ROOM_W + HALL_D * 0.6, ROOM_D * 0.7)
    devs = [
        ({"id": "tablet-mac", "kind": "WIFI", "rate": 3, "pos": lambda t: hall, "data_ratio": 0.7}, 0, total),
        ({"id": "hotspot-mac", "kind": "WIFI", "rate": 10, "pos": lambda t: (ROOM_W + 90, ROOM_D * 0.3),
          "data_ratio": 0.1}, 0, total),
        ({"id": "esp32cam-hidden", "kind": "WIFI", "rate": 8, "pos": lambda t: seat_xy(4, 5), "data_ratio": 0.9},
         20, total),
        ({"id": "hall-walker", "kind": "BLE", "rate": 4,
          "pos": lambda t: (ROOM_W + 90, -100 + (ROOM_D + 200) * (t - 40) / 15)}, 40, 55),
    ]
    for d, a, b in devs:
        sim.emit(d, a, b, rng, rows, sim.WALL_DB)
    rows.sort(key=lambda r: r[0])
    return rows


def exam_started(url):
    try:
        with urllib.request.urlopen(url, timeout=0.5) as r:
            return json.load(r).get("phase") in ("시험 중", "쉬는 시간")
    except Exception:
        return None


def live_scenario(f, rng, url, after, auto_start):
    """1초씩 만들어 쓴다. 시험 시작을 서버에서 확인한 뒤에야 숨긴 기기를 켠다 (기준 측정에 섞이지 않게)."""
    hall = (ROOM_W + HALL_D * 0.6, ROOM_D * 0.7)
    base = [{"id": "tablet-mac", "kind": "WIFI", "rate": 3, "pos": lambda t: hall, "data_ratio": 0.7},
            {"id": "hotspot-mac", "kind": "WIFI", "rate": 10, "pos": lambda t: (ROOM_W + 90, ROOM_D * 0.3), "data_ratio": 0.1}]
    cam = {"id": "esp32cam-hidden", "kind": "WIFI", "rate": 8, "pos": lambda t: seat_xy(4, 5), "data_ratio": 0.9}
    t0, k, es = time.time(), 0, None
    print("원래 있던 기기(태블릿·핫스팟) 켬. 태블릿에서 [① 기준 측정] → 30초 이상 → [② 시험 시작]을 누르세요.")
    while es is None or k < es + after:
        if es is None:
            st = exam_started(url)
            if st or (st is None and auto_start and k >= auto_start):
                es = k
                print(f"  {k}s 시험 시작 확인 → +5초 숨긴 카메라(4줄 5열), +25초 복도 통행")
        rows = []
        for d in base:
            sim.emit(d, k, k + 1, rng, rows, sim.WALL_DB)
        if es is not None and k >= es + 5:
            sim.emit(cam, k, k + 1, rng, rows, sim.WALL_DB)
        if es is not None and es + 25 <= k < es + 40:
            w0 = es + 25
            walker = {"id": "hall-walker", "kind": "BLE", "rate": 4,
                      "pos": lambda t, w0=w0: (ROOM_W + 90, -100 + (ROOM_D + 200) * (t - w0) / 15)}
            sim.emit(walker, k, k + 1, rng, rows, sim.WALL_DB)
        for t, s_, kd, i, v, fr, n in sorted(rows, key=lambda r: r[0]):
            wait = t0 + t - time.time()
            if wait > 0:
                time.sleep(wait)
            f.write(f"{t0 + t:.3f},{s_},{kd},{hash_id(i)},{v},{fr},{n}\n")
        wait = t0 + k + 1 - time.time()
        if wait > 0:
            time.sleep(wait)
        k += 1
    print("끝")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--seconds", type=float, default=130, help="(보정 연습) 길이 / (시연) 시험 시작 후 더 돌릴 초")
    ap.add_argument("--calib-demo", action="store_true", help="보정 연습 시나리오")
    ap.add_argument("--server", default="http://localhost:8000/state")
    ap.add_argument("--auto-start", type=float, default=0, help="서버 없이 돌릴 때 이 초 뒤 시험 시작으로 침")
    a = ap.parse_args()
    new = not os.path.exists(a.out)
    f = open(a.out, "a", buffering=1, encoding="utf-8")
    if new:
        f.write("t,sensor,kind,id,rssi,frame,n\n")
    rng = np.random.default_rng(0)
    if not a.calib_demo:
        live_scenario(f, rng, a.server, a.seconds, a.auto_start)
        raise SystemExit
    rows = calib_demo(rng, a.seconds)
    t0 = time.time()
    print(f"가짜 센서 시작 → {a.out}  ({len(rows)}줄, {a.seconds:.0f}초)")
    for t, s_, k, i, v, fr, n in rows:
        wait = t0 + t - time.time()
        if wait > 0:
            time.sleep(wait)
        f.write(f"{t0 + t:.3f},{s_},{k},{hash_id(i)},{v},{fr},{n}\n")
    print("끝")

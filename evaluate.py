"""성공 기준 점검 — 시연 페이지의 숫자와 같은 기준으로 잰다.

  구역 정확도 ≥ 80%, 복도 오탐 ≤ 10%, 숨긴 기기 10회 중 9회+ (Wi-Fi·BT 각각), 잘못된 경보 0회

기본은 시뮬레이션 데이터. 실제 데이터가 생기면 --calib-train / --calib-test 로 바꿔 넣는다.
    python evaluate.py
    python evaluate.py --wall-db 10        # 알루미늄 테이프 벽 가정
    python evaluate.py --calib-train data/real_day1.csv --calib-test data/real_day2.csv
"""
import argparse
from collections import Counter
import numpy as np

import sim
from config import INSIDE, CENTER, HALL, HOLD, MIN_SENSORS, EXAM_MIN
from pipeline import (Locator, windowize, load_rows, load_labels, analyze, WINDOW_S)


def zone_eval(loc, rows, labels):
    wins = windowize(rows)
    truth, vecs = [], []
    for start, end, dev, zone in labels:
        for w in wins.get(dev, []):
            if w["t"] >= start and w["t"] + WINDOW_S <= end and w["n_sensors"] >= MIN_SENSORS:
                truth.append(zone)
                vecs.append(w["vec"])
    from pipeline import alive_cols
    pred = loc.predict(vecs, alive_cols(rows, max(r[0] for r in rows) + 1, span=1e9))
    pairs = list(zip(truth, pred))
    decided = [(t, p) for t, p in pairs if p != HOLD]
    acc = np.mean([t == p for t, p in decided]) if decided else 0
    hold = 1 - len(decided) / len(pairs)
    hall_wrong = [p for t, p in decided if t == HALL and p != HALL]
    hall_n = sum(1 for t, _ in decided if t == HALL)
    into_inside = [p for t, p in decided if t == HALL and p in INSIDE + [CENTER]]
    print(f"[1단계 위치] 창 {len(pairs)}개  정확도 {acc:.1%} (보류 제외)  보류 {hold:.1%}")
    print(f"           복도 → 교실 안으로 잘못 판정 {len(into_inside)}/{hall_n} = {len(into_inside)/max(hall_n,1):.1%}")
    conf = Counter((t, p) for t, p in decided if t != p)
    if conf:
        print("           자주 틀린 쌍:", ", ".join(f"{t}→{p} {c}" for (t, p), c in conf.most_common(4)))
    return acc, len(into_inside) / max(hall_n, 1)


def exam_eval(loc, runs, wall_db, base_seed=100, dead=None):
    det = Counter()
    tot = Counter()
    false_alarm = 0
    watch_ok = 0
    examples = []
    for i in range(runs):
        for variant in ("cam", "ear", "glasses"):
            rows, truth, _ = sim.make_exam(base_seed + i * 7 + {"cam": 0, "ear": 1, "glasses": 2}[variant], wall_db=wall_db, variant=variant)
            if dead:
                rows = [r for r in rows if r[1] != dead]
            sig = analyze(rows, loc, now=EXAM_MIN * 60)
            tot[variant] += 1
            found = False
            for s in sig:
                lv = [truth[i][0] for i in s["ids"] if i in truth]
                t = "높음" if "높음" in lv else ("관찰" if "관찰" in lv else "낮음")
                if t == "높음" and s["level"] == "높음":
                    found = True
                if t == "낮음" and s["level"] == "높음":
                    false_alarm += 1
                    examples.append((variant, [truth[i][1] for i in s["ids"]][0], s["why"]))
                if t == "관찰" and s["level"] in ("관찰", "높음"):
                    watch_ok += 1
            det[variant] += found
    names = {"cam": "Wi-Fi 카메라", "ear": "BLE 이어폰", "glasses": "AI 안경(MAC 교체)"}
    print(f"[2단계 의심도] 시험 {sum(tot.values())}회 시뮬레이션")
    for v in tot:
        print(f"           숨긴 {names[v]}: {det[v]}/{tot[v]} 회 '높음'")
    print(f"           짧게 켜진 기기 → 관찰 이상: {watch_ok}/{sum(tot.values())}")
    print(f"           잘못된 경보(낮음이어야 하는데 높음): {false_alarm} 회")
    for e in examples[:5]:
        print("             ·", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--wall-db", type=float, default=sim.WALL_DB)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--calib-train")
    ap.add_argument("--calib-test")
    ap.add_argument("--dead", help="이 센서가 고장 났다고 가정 (예: D)")
    a = ap.parse_args()
    if a.calib_train:
        tr_rows, tr_lab = load_rows(a.calib_train), load_labels(a.calib_train.replace(".csv", "_labels.csv"))
        te_rows, te_lab = load_rows(a.calib_test), load_labels(a.calib_test.replace(".csv", "_labels.csv"))
    else:
        tr_rows, tr_lab = sim.make_calib(1, wall_db=a.wall_db)   # 1일차 = 학습
        te_rows, te_lab = sim.make_calib(2, wall_db=a.wall_db)   # 2일차 = 시험
    loc = Locator().fit(tr_rows, tr_lab)
    if a.dead:
        te_rows = [r for r in te_rows if r[1] != a.dead]
    print(f"벽 감쇠 {a.wall_db} dB 가정, 지문 {len(loc.y)}개로 학습" + (f", 센서 {a.dead} 고장 가정" if a.dead else "") + "\n")
    zone_eval(loc, te_rows, te_lab)
    print()
    exam_eval(loc, a.runs, a.wall_db, dead=a.dead)

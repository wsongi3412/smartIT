"""기준값 실험 — config.py 의 숫자를 바꿔 보며 성공 기준이 어떻게 변하는지 표로 만든다.

    python experiments/tune.py              # 가짜 데이터 (지금)
    python experiments/tune.py --calib1 data/calib_day1.csv --calib2 data/calib_day2.csv
                                            # 실측 신호 지도로 1·2·3번 실험 (4·5번은 시험 기록이 필요해서 가짜 데이터)

결과: results/tuning_<시각>.md  (표 + 어떤 값을 고를지)

실험
  1) K / MIN_VOTES   : 가장 비슷한 기록 몇 개에게 물어보고 몇 표면 확정하나
  2) ABS_WEIGHT      : 판정에 "가장 센 값"을 얼마나 반영하나 (벽 정보)
  3) 송신 세기         : 대역 기기 신호를 약하게 하면? (가짜 데이터에서만)
  4) HIGH_MIN        : 교실 안 몇 분이면 '높음' — 놓침·잘못된 경보·걸리는 시간
  5) MERGE_DIST      : MAC이 바뀐 신호를 이어 붙이는 허용 차이
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

import config
import pipeline
import sim
from run_all import zone_score, load_calib

TARGET_ZONE, TARGET_HALL = 0.80, 0.10
SNAP = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]    # 의심도 누적을 보는 시점(분)
VARIANTS = ("cam", "ear", "glasses")
NAMES = {"cam": "카메라", "ear": "이어폰", "glasses": "AI 안경"}


def setp(**kw):
    """pipeline 모듈 안의 기준값을 바꾼다 (config 를 import 할 때 값이 복사되므로 둘 다)."""
    for k, v in kw.items():
        setattr(pipeline, k, v)
        setattr(config, k, v)


def reset():
    setp(K=5, MIN_VOTES=3, ABS_WEIGHT=0.5, HIGH_MIN=20, MERGE_DIST=6.0)


def exams(runs, base=500):
    out = []
    for i in range(runs):
        for j, v in enumerate(VARIANTS):
            rows, truth, _ = sim.make_exam(base + i * 7 + j, variant=v)
            out.append((v, rows, {k: lv for k, (lv, _) in truth.items()}))
    return out


def truth_of(s, truth):
    lv = [truth.get(i, "낮음") for i in s["ids"]]
    return "높음" if "높음" in lv else ("관찰" if "관찰" in lv else "낮음")


def exam_metrics(loc, ex):
    """시험 끝(50분) 기준: 변형별 숨긴 기기 '높음' 여부, 잘못된 경보 수"""
    det = {v: [0, 0] for v in VARIANTS}
    false = 0
    for v, rows, truth in ex:
        found = False
        for s in pipeline.analyze(rows, loc, now=config.EXAM_MIN * 60):
            if s["baseline"]:
                continue
            t = truth_of(s, truth)
            if t == "높음" and s["level"] == "높음":
                found = True
            if t == "낮음" and s["level"] == "높음":
                false += 1
        det[v][0] += found
        det[v][1] += 1
    return det, false


def pct(x):
    return f"{x:.0%}"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib1")
    ap.add_argument("--calib2")
    ap.add_argument("--runs", type=int, default=10, help="변형별 가짜 시험 횟수")
    a = ap.parse_args()
    real = bool(a.calib1)
    t0 = time.time()
    c1 = load_calib(a.calib1) if real else sim.make_calib(1)
    c2 = load_calib(a.calib2 or a.calib1) if real else sim.make_calib(2)
    L = [f"# 기준값 실험 결과 {'(실측 신호 지도)' if real else '(가짜 데이터 — 코드·방향 확인용)'}",
         "", f"- 생성: {time.strftime('%Y-%m-%d %H:%M')}",
         f"- 시험 시뮬레이션: 변형(카메라·이어폰·AI 안경)별 {a.runs}회", ""]

    # 1) K / MIN_VOTES
    print("[1/5] K / MIN_VOTES")
    reset()
    ex = exams(a.runs)
    rows = []
    for k, mv in ((3, 2), (5, 3), (5, 4), (7, 4), (9, 5)):
        setp(K=k, MIN_VOTES=mv)
        z = zone_score(pipeline.Locator(k=k).fit(*c1), *c2)
        rows.append([f"k={k}, {mv}표", pct(z["acc"]), pct(z["hall_in"]), pct(z["hold"]),
                     "✅" if z["acc"] >= TARGET_ZONE and z["hall_in"] <= TARGET_HALL else ""])
        print("   ", rows[-1])
    L += ["## 1. K / MIN_VOTES (가장 비슷한 기록 몇 개, 몇 표면 확정)", "",
          *table(["설정", "구역 정확도", "복도→교실 오판", "판단 보류", "목표 통과"], rows), ""]
    reset()

    # 2) ABS_WEIGHT
    print("[2/5] ABS_WEIGHT")
    rows = []
    for w in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
        setp(ABS_WEIGHT=w)
        z = zone_score(pipeline.Locator().fit(*c1), *c2)
        rows.append([w, pct(z["acc"]), pct(z["hall_in"]), pct(z["hold"]),
                     "✅" if z["acc"] >= TARGET_ZONE and z["hall_in"] <= TARGET_HALL else ""])
        print("   ", rows[-1])
    L += ["## 2. ABS_WEIGHT (가장 센 값 반영 정도)", "", "0이면 상대값만 씀 (벽 정보 없음).", "",
          *table(["ABS_WEIGHT", "구역 정확도", "복도→교실 오판", "판단 보류", "목표 통과"], rows), ""]
    reset()

    # 3) 송신 세기 (가짜 데이터만)
    if not real:
        print("[3/5] 송신 세기")
        rows = []
        base_tx = dict(sim.TX_10CM)
        for off in (0, -10, -20, -30):
            sim.TX_10CM.update({k: v + off for k, v in base_tx.items()})
            z = zone_score(pipeline.Locator().fit(*sim.make_calib(1)), *sim.make_calib(2))
            rows.append([f"{off:+d} dB" if off else "기본", pct(z["acc"]), pct(z["hall_in"]), pct(z["hold"])])
            print("   ", rows[-1])
        sim.TX_10CM.update(base_tx)
        L += ["## 3. 대역 기기 송신 세기", "",
              "가짜 데이터는 거리·벽 공식이라 세기를 줄여도 상대값은 그대로이고, 너무 약하면 센서가 못 듣는 창만 늘어난다. **실측에서 꼭 다시 볼 항목.**", "",
              *table(["송신 세기", "구역 정확도", "복도→교실 오판", "판단 보류"], rows), ""]

    # 4) HIGH_MIN — 누적 상태를 시점별로 한 번 계산해 두고 기준만 바꿔 본다
    print("[4/5] HIGH_MIN (시점별 누적 계산, 1~2분 걸림)")
    reset()
    loc = pipeline.Locator().fit(*c1)
    traj = []     # (변형, 정답, {분: (교실안분, 교실안비율, 기준선)})
    for v, rows_, truth in ex:
        per = {}
        for m in SNAP:
            for s in pipeline.analyze(rows_, loc, now=m * 60):
                if s["baseline"]:
                    continue
                key = s["ids"][0]
                per.setdefault(key, {"t": truth_of(s, truth), "v": v, "m": {}})
                per[key]["m"][m] = (s["f"]["inside_min"], s["f"]["inside_ratio"])
        traj += list(per.values())
    rows = []
    for hm in (10, 15, 20, 25, 30):
        hit = {x: [0, 0] for x in VARIANTS}
        first = []
        false = watch_hi = 0
        for tr in traj:
            lv_at = {m: ("높음" if (r >= config.INSIDE_RATIO and im >= hm) else "x") for m, (im, r) in tr["m"].items()}
            hi_end = lv_at.get(50) == "높음"
            if tr["t"] == "높음":
                hit[tr["v"]][1] += 1
                hit[tr["v"]][0] += hi_end
                ms = [m for m in SNAP if lv_at.get(m) == "높음"]
                if ms:
                    first.append(min(ms))
            elif tr["t"] == "관찰" and hi_end:
                watch_hi += 1
            elif tr["t"] == "낮음" and hi_end:
                false += 1
        rows.append([f"{hm}분", *[f"{hit[x][0]}/{hit[x][1]}" for x in VARIANTS],
                     f"{np.mean(first):.0f}분" if first else "-", false, watch_hi])
        print("   ", rows[-1])
    L += ["## 4. HIGH_MIN ('높음'이 되는 교실 안 누적 시간)", "",
          "숨긴 기기는 시험 2~15분 사이에 켜짐. '처음 높음'은 5분 간격으로 본 평균. '짧은 기기→높음'은 3~6분만 켜졌던 기기가 높음까지 올라간 수(낮을수록 좋음).", "",
          *table(["HIGH_MIN", *[f"{NAMES[x]} 높음" for x in VARIANTS], "처음 높음(평균)", "잘못된 경보", "짧은 기기→높음"], rows), ""]
    reset()

    # 5) MERGE_DIST
    print("[5/5] MERGE_DIST")
    rows = []
    gl = [e for e in ex if e[0] == "glasses"]
    for md in (2.0, 4.0, 6.0, 10.0, 15.0):
        setp(MERGE_DIST=md)
        det, false = exam_metrics(loc, gl + [e for e in ex if e[0] != "glasses"][: a.runs])
        n_tracks = []
        for v, rows_, truth in gl:
            sig = [s for s in pipeline.analyze(rows_, loc, now=3000) if not s["baseline"] and truth_of(s, truth) == "높음"]
            n_tracks.append(len(sig))
        rows.append([md, f"{det['glasses'][0]}/{det['glasses'][1]}", f"{np.mean(n_tracks):.1f}", false])
        print("   ", rows[-1])
    L += ["## 5. MERGE_DIST (MAC이 바뀐 신호를 같은 기기로 잇는 허용 차이, dB)", "",
          "AI 안경은 8~15분마다 MAC을 바꿈. '조각 수'는 한 안경이 몇 개 신호로 쪼개져 보였나(1이 이상적). 너무 크면 다른 기기까지 이어 붙일 위험.", "",
          *table(["MERGE_DIST", "AI 안경 높음", "안경 조각 수(평균)", "잘못된 경보"], rows), ""]
    reset()

    os.makedirs("results", exist_ok=True)
    path = os.path.join("results", time.strftime("tuning_%Y%m%d_%H%M") + ("" if real else "_sim") + ".md")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n완료 {time.time() - t0:.0f}초 → {path}")

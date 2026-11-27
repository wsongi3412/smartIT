"""한 번에 돌리기: 신호 지도 → 위치 AI 채점 → 시험 기록 채점 → 의심도 AI 학습·비교 → 보고서

    python run_all.py                       # 데모: 가짜 데이터로 전체 흐름 (지금 바로)
    python run_all.py --calib1 data/calib_day1.csv --calib2 data/calib_day2.csv \\
                      --exams1 data/exams/day1 --exams2 data/exams/day2

결과는 results/<날짜_시각>/ 에 저장:
    report.md          발표용 수치 요약 (목표 대비 통과/미달)
    confusion.png      혼동 행렬 그림 (실제 구역 × 판정 구역)
    confusion.csv      같은 내용 숫자
    signals.csv        시험별·신호별 판정 결과 (잘못된 경보 찾을 때)
    rf.pkl             의심도 AI 모델 (server.py --model 로 사용)

입력 파일 (실측):
    신호 지도  : calib_dayN.csv + calib_dayN_labels.csv   (serial_reader.py + stage_log.py)
    시험 기록  : 폴더 안의 exam_*.csv + _truth.csv (+ _meta.json)  (server.py --live 가 시험 끝날 때 자동 저장)
                 _truth.csv 의 level 칸(높음/관찰/낮음)은 사람이 채운다. 적지 않은 신호는 '낮음'으로 본다.
"""
import argparse
import csv
import glob
import json
import os
import pickle
import time
from collections import Counter

import numpy as np

import sim
from config import ALL_ZONES, INSIDE, CENTER, HALL, HOLD, MIN_SENSORS, SENSOR_IDS, EXAM_MIN, hash_id
from pipeline import (Locator, windowize, load_rows, load_labels, analyze, alive_cols,
                      level_from_proba, RF_FEATURES, WINDOW_S, RFModel)

TARGET = {"zone": 0.80, "hall": 0.10, "detect": 0.90, "false": 0}
LEVELS = ["낮음", "관찰", "높음"]


# ---------------- 입력 ----------------
def load_calib(path):
    return load_rows(path), load_labels(path.replace(".csv", "_labels.csv"))


def load_exams(folder):
    """→ [(이름, rows, truth{id: level}, scale, end)]"""
    out = []
    for f in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        if f.endswith("_truth.csv"):
            continue
        base = f[:-4]
        truth = {}
        if os.path.exists(base + "_truth.csv"):
            with open(base + "_truth.csv", encoding="utf-8") as tf:
                for line in tf:
                    if line.startswith("#") or line.startswith("id,"):
                        continue
                    p = [x.strip() for x in line.rstrip("\n").split(",")]
                    if len(p) >= 2 and p[0] and p[1] in LEVELS:
                        truth[hash_id(p[0]) if ":" in p[0] else p[0]] = p[1]
        meta = {}
        if os.path.exists(base + "_meta.json"):
            meta = json.load(open(base + "_meta.json", encoding="utf-8"))
        rows = load_rows(f)
        out.append((os.path.basename(base), rows, truth, float(meta.get("scale", 1.0)),
                    float(meta.get("end", max(r[0] for r in rows)))))
    return out


def demo_exams(seeds):
    out = []
    for sd in seeds:
        rows, truth, v = sim.make_exam(sd)
        out.append((f"sim_{sd}_{v}", rows, {k: lv for k, (lv, _) in truth.items()}, 1.0, EXAM_MIN * 60.0))
    return out


# ---------------- 1단계: 위치 ----------------
def zone_score(loc, rows, labels):
    wins = windowize(rows)
    truth, vecs = [], []
    for start, end, dev, zone in labels:
        for w in wins.get(dev, []):
            if w["t"] >= start and w["t"] + WINDOW_S <= end and w["n_sensors"] >= MIN_SENSORS:
                truth.append(zone)
                vecs.append(w["vec"])
    cols = alive_cols(rows, max(r[0] for r in rows) + 1, span=1e12)
    pred = loc.predict(vecs, cols)
    dec = [(t, p) for t, p in zip(truth, pred) if p != HOLD]
    hall = [p for t, p in dec if t == HALL]
    return {
        "n": len(truth),
        "acc": float(np.mean([t == p for t, p in dec])) if dec else 0.0,
        "hold": 1 - len(dec) / max(len(truth), 1),
        "hall_in": sum(1 for p in hall if p in INSIDE + [CENTER]) / max(len(hall), 1),
        "pairs": list(zip(truth, pred)),
    }


def dead_sensor_scores(loc, rows, labels):
    return {s: zone_score(loc, [r for r in rows if r[1] != s], labels)["acc"] for s in SENSOR_IDS}


def save_confusion(pairs, outdir):
    cols = ALL_ZONES + [HOLD]
    m = np.zeros((len(ALL_ZONES), len(cols)), int)
    for t, p in pairs:
        m[ALL_ZONES.index(t), cols.index(p)] += 1
    with open(os.path.join(outdir, "confusion.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["실제\\판정"] + cols)
        for z, row in zip(ALL_ZONES, m):
            w.writerow([z] + row.tolist())
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        have = {f.name for f in font_manager.fontManager.ttflist}
        kr = [n for n in ("AppleGothic", "Apple SD Gothic Neo", "Malgun Gothic", "NanumGothic", "Noto Sans CJK KR") if n in have]
        plt.rcParams["font.family"] = kr[:1] or ["DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        frac = m / np.maximum(m.sum(1, keepdims=True), 1)
        fig, ax = plt.subplots(figsize=(7, 5.2), dpi=160)
        ax.imshow(frac, cmap="Blues", vmin=0, vmax=1)
        ax.set_xticks(range(len(cols)), cols, rotation=30, ha="right")
        ax.set_yticks(range(len(ALL_ZONES)), ALL_ZONES)
        ax.set_xlabel("AI 판정")
        ax.set_ylabel("실제 위치")
        for i in range(m.shape[0]):
            for j in range(m.shape[1]):
                if m[i, j]:
                    ax.text(j, i, f"{frac[i, j]:.0%}", ha="center", va="center", fontsize=8,
                            color="white" if frac[i, j] > 0.55 else "#16202a")
        ax.set_title("위치 판정 혼동 행렬 (행 = 실제, 비율)")
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, "confusion.png"))
        plt.close(fig)
        return True
    except Exception as e:
        print("그림 저장 실패:", e)
        return False


# ---------------- 2단계: 의심도 ----------------
def truth_of(sig, truth):
    lv = [truth.get(i, "낮음") for i in sig["ids"]]
    return "높음" if "높음" in lv else ("관찰" if "관찰" in lv else "낮음")


def exam_score(loc, exams, model=None, sig_rows=None, tag=""):
    hi_tot = hi_ok = watch_tot = watch_ok = false_alarm = 0
    for name, rows, truth, scale, end in exams:
        for s in analyze(rows, loc, now=end, scale=scale, model=model):
            if s["baseline"]:
                continue
            t = truth_of(s, truth)
            if t == "높음":
                hi_tot += 1
                hi_ok += s["level"] == "높음"
            elif t == "관찰":
                watch_tot += 1
                watch_ok += s["level"] in ("관찰", "높음")
            elif s["level"] == "높음":
                false_alarm += 1
            if sig_rows is not None:
                sig_rows.append([tag, name, "/".join(s["ids"]), s["kind"], s["near"], s["minutes"],
                                 s["inside"], t, s["level"], s["why"]])
    return {"hi": (hi_ok, hi_tot), "watch": (watch_ok, watch_tot), "false": false_alarm}


def rf_dataset(loc, exams):
    X, y = [], []
    for name, rows, truth, scale, end in exams:
        for frac in (0.2, 0.4, 0.6, 0.8, 1.0):     # 시험 중 여러 시점의 누적 상태
            for s in analyze(rows, loc, now=end * frac, scale=scale):
                if s["baseline"]:
                    continue
                X.append([s["f"][k] for k in RF_FEATURES])
                y.append(LEVELS.index(truth_of(s, truth)))
    return np.array(X), np.array(y)


def train_rf(loc, exams):
    from sklearn.ensemble import RandomForestClassifier
    X, y = rf_dataset(loc, exams)
    if len(set(y.tolist())) < 2:
        return None, "학습 데이터에 등급이 한 종류뿐이라 학습 생략"

    rf = RandomForestClassifier(n_estimators=200, max_depth=6, min_samples_leaf=5,
                                class_weight="balanced", random_state=0).fit(X, y)
    imp = sorted(zip(RF_FEATURES, rf.feature_importances_), key=lambda x: -x[1])[:5]
    return RFModel(rf), ", ".join(f"{k} {v:.2f}" for k, v in imp) + f"  (학습 예 {len(y)}개 {dict(Counter(LEVELS[i] for i in y))})"


# ---------------- 보고서 ----------------
def mark(ok):
    return "✅ 통과" if ok else "❌ 미달"


def frac(a):
    return f"{a[0]}/{a[1]}" if a[1] else "-"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib1", help="신호 지도 1일차 (학습)")
    ap.add_argument("--calib2", help="신호 지도 2일차 (검증)")
    ap.add_argument("--exams1", help="시험 기록 폴더 1일차 (의심도 AI 학습)")
    ap.add_argument("--exams2", help="시험 기록 폴더 2일차 (채점)")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    demo = not a.calib1
    outdir = os.path.join(a.out, time.strftime("%Y%m%d_%H%M%S") + ("_demo" if demo else ""))
    os.makedirs(outdir, exist_ok=True)
    print(f"{'가짜 데이터 데모' if demo else '실측 데이터'} → {outdir}\n")

    # 1) 위치 AI
    print("[1/4] 신호 지도로 위치 AI 학습·채점")
    c1 = sim.make_calib(1) if demo else load_calib(a.calib1)
    c2 = sim.make_calib(2) if demo else load_calib(a.calib2 or a.calib1)
    loc = Locator().fit(*c1)
    z = zone_score(loc, *c2)
    dead = dead_sensor_scores(loc, *c2)
    has_png = save_confusion(z["pairs"], outdir)
    print(f"      구역 정확도 {z['acc']:.1%}, 복도 오판 {z['hall_in']:.1%}, 보류 {z['hold']:.1%}")

    # 2) 시험 기록
    print("[2/4] 시험 기록 불러오기")
    ex1 = demo_exams(range(1000, 1020)) if demo else (load_exams(a.exams1) if a.exams1 else [])
    ex2 = demo_exams(range(2000, 2015)) if demo else (load_exams(a.exams2) if a.exams2 else [])
    print(f"      학습용 {len(ex1)}회, 채점용 {len(ex2)}회")

    # 3) 의심도: 규칙 vs RF
    print("[3/4] 의심도 채점 (규칙) + AI 학습")
    sig_rows = []
    rule = exam_score(loc, ex2, sig_rows=sig_rows, tag="규칙") if ex2 else None
    model, info = (train_rf(loc, ex1) if ex1 else (None, "1일차 시험 기록이 없어 학습 생략"))
    rf = exam_score(loc, ex2, model=model, sig_rows=sig_rows, tag="RF") if (model and ex2) else None
    if model:
        with open(os.path.join(outdir, "rf.pkl"), "wb") as f:
            pickle.dump(model, f)
    with open(os.path.join(outdir, "signals.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["방식", "시험", "신호", "종류", "부근", "교실안_분", "교실안_비율", "정답", "판정", "근거"])
        w.writerows(sig_rows)

    # 4) 보고서
    print("[4/4] 보고서 작성")
    L = [f"# ExamSentry 결과 보고서 {'(가짜 데이터 데모 — 발표용 아님)' if demo else '(실측)'}",
         "", f"- 생성: {time.strftime('%Y-%m-%d %H:%M')}",
         f"- 신호 지도: 학습 {'sim day1' if demo else a.calib1} / 검증 {'sim day2' if demo else (a.calib2 or a.calib1)}"
         + ("" if demo or a.calib2 else "  ⚠️ 같은 날 데이터로 검증함 (2일차 측정 필요)"),
         f"- 시험 기록: 학습 {len(ex1)}회 / 채점 {len(ex2)}회", "",
         "## 성공 기준", "", "| 지표 | 목표 | 결과 | |", "|---|---|---|---|",
         f"| 구역 정확도 (보류 제외) | ≥ 80% | {z['acc']:.1%} | {mark(z['acc'] >= TARGET['zone'])} |",
         f"| 복도 → 교실 안 잘못 판정 | ≤ 10% | {z['hall_in']:.1%} | {mark(z['hall_in'] <= TARGET['hall'])} |"]
    for name, r in (("규칙", rule), ("RF", rf)):
        if r:
            ok = r["hi"][1] and r["hi"][0] / r["hi"][1] >= TARGET["detect"]
            L.append(f"| 숨긴 기기 '높음' ({name}) | 90% 이상 | {frac(r['hi'])} | {mark(ok)} |")
            L.append(f"| 잘못된 경보 ({name}) | 0회 | {r['false']}회 | {mark(r['false'] == 0)} |")
    L += ["", "## 위치 판정", "",
          f"판단 보류 {z['hold']:.1%} (창 {z['n']}개).", "",
          "| 고장 가정 센서 | 남은 센서로 구역 정확도 |", "|---|---|"]
    L += [f"| {s} | {v:.1%} |" for s, v in dead.items()]
    if has_png:
        L += ["", "![혼동 행렬](confusion.png)"]
    L += ["", "## 의심도", "", f"- 랜덤포레스트 중요 특징: {info}"]
    for name, r in (("규칙", rule), ("RF", rf)):
        if r:
            L.append(f"- {name}: 숨긴 기기 '높음' {frac(r['hi'])}, 짧게 켜진 기기 '관찰 이상' {frac(r['watch'])}, 잘못된 경보 {r['false']}회")
    L += ["", "신호별 판정은 `signals.csv` 에서 '정답'과 '판정'이 다른 줄을 찾아 원인을 확인합니다.",
          "", "> 발표에는 신호 지도에 쓰지 않은 날 측정한 실측 결과만 씁니다."]
    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n" + "\n".join(L[7:13 + (4 if rf else 2)]))
    print(f"\n보고서 → {outdir}/report.md")

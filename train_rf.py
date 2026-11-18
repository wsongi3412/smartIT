"""의심도 AI(랜덤포레스트) 학습 — 1일차로 학습, 2일차로 시험 (날짜로 나눔).

지금은 시뮬레이션 시험 여러 회로 학습 흐름을 검증한다. 실제 수집 데이터가 생기면
make_day() 대신 실제 시험 CSV + 연출 기록(신호별 정답 등급)을 넣는다.

    python train_rf.py               → data/rf.pkl 저장, 2일차 성능 출력
    python server.py --model data/rf.pkl
"""
import pickle
from collections import Counter
import numpy as np
from sklearn.ensemble import RandomForestClassifier

import sim
from config import EXAM_MIN
from pipeline import Locator, analyze, level_from_proba, level_rule, FEATURES, RF_FEATURES

SNAP_MIN = [10, 20, 30, 40, 50]   # 시험 중 여러 시점의 '누적 상태'를 모두 학습 예로 씀


def make_day(loc, seeds):
    X, y, meta = [], [], []
    for sd in seeds:
        rows, truth, _ = sim.make_exam(sd)
        for m in SNAP_MIN:
            for s in analyze(rows, loc, now=m * 60):
                if s["baseline"]:
                    continue
                lv = [truth[i][0] for i in s["ids"] if i in truth]
                X.append([s["f"][k] for k in RF_FEATURES])
                y.append(2 if "높음" in lv else (1 if "관찰" in lv else 0))   # 0 낮음 / 1 관찰 / 2 높음
                meta.append((m, "높음" if "높음" in lv else ("관찰" if "관찰" in lv else "낮음"), s["f"]))
    return np.array(X), np.array(y), meta


if __name__ == "__main__":
    loc = Locator().fit(*sim.make_calib(1))
    Xtr, ytr, _ = make_day(loc, range(1000, 1030))   # 1일차
    Xte, yte, mte = make_day(loc, range(2000, 2015))  # 2일차
    rf = RandomForestClassifier(n_estimators=200, max_depth=6, min_samples_leaf=5, random_state=0,
                                class_weight="balanced").fit(Xtr, ytr)
    print(f"학습 {len(ytr)}개, 시험 {len(yte)}개 (등급별 {dict(Counter(ytr.tolist()))})\n")
    for name, pred in [("규칙", [level_rule({**f, "in_baseline": 0})[0] for _, _, f in mte]),
                       ("RF", [level_from_proba(x) for x in rf.predict_proba(Xte)])]:
        print(f"[{name}] 정답 등급 → 판정 등급 (시험 끝 50분 시점)")
        c = Counter((t, q) for (m, t, _), q in zip(mte, pred) if m == EXAM_MIN)
        for t in ("높음", "관찰", "낮음"):
            print(f"   {t}: " + "  ".join(f"{q} {c[(t, q)]}" for q in ("높음", "관찰", "낮음")))
    imp = sorted(zip(RF_FEATURES, rf.feature_importances_), key=lambda x: -x[1])
    print("\n중요 특징:", ", ".join(f"{k} {v:.2f}" for k, v in imp[:5]))
    with open("data/rf.pkl", "wb") as f:
        pickle.dump(rf, f)
    print("저장 → data/rf.pkl")

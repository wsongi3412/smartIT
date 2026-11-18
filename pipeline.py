"""ExamSentry 분석 파이프라인: 수집 행 → 2초 창 → 위치 판정(k-NN) → 신호 묶기 → 의심도.

입력 CSV 형식은 sim.py / serial_reader.py 와 같다:  t,sensor,kind,id,rssi,frame,n
t=0 이 시험 시작. t<0 구간에 잡힌 신호는 '시험 전 기준선'.
"""
import csv
from collections import Counter, defaultdict
import numpy as np
from sklearn.neighbors import KNeighborsClassifier

from config import (USE_ABS, ABS_WEIGHT, SENSOR_IDS, INSIDE, CENTER, HALL, HOLD, WINDOW_S, MISSING, MIN_SENSORS, K,
                    MIN_VOTES, SMOOTH, HIGH_MIN, WATCH_MIN, INSIDE_RATIO, REAPPEAR_GAP, MERGE_GAP, MERGE_DIST,
                    PROB_WATCH, PROB_HIGH)

FEATURES = ["seen_ratio", "inside_ratio", "zone_changes", "reappear", "pkt_per_sec",
            "data_frame_ratio", "mean_rssi", "in_baseline", "is_wifi", "inside_min"]
# RF 입력에서는 mean_rssi 제외: 기기 송신 세기에 따라 달라서 '대역 기기'를 외워 버릴 위험
RF_FEATURES = [k for k in FEATURES if k != "mean_rssi"]


# ---------------- 읽기 ----------------
def load_rows(path):
    with open(path) as f:
        r = csv.reader(f)
        next(r)
        return [(float(t), s, k, i, int(v), fr, int(n)) for t, s, k, i, v, fr, n in r]


def load_labels(path):
    with open(path) as f:
        r = csv.DictReader(f)
        return [(float(x["start"]), float(x["end"]), x["id"], x["zone"]) for x in r]


# ---------------- 2초 창 ----------------
def windowize(rows):
    """→ {id: [창, ...]} 창 = dict(w, t, vec, n_sensors, pkts, data, kind)"""
    acc = defaultdict(lambda: {"r": defaultdict(list), "pkts": 0, "data": 0, "kind": None})
    for t, s, k, i, v, fr, n in rows:
        a = acc[(i, int(np.floor(t / WINDOW_S)))]
        a["r"][s].append(v)
        a["pkts"] += n
        a["data"] += n if fr == "D" else 0
        a["kind"] = k
    out = defaultdict(list)
    for (i, w), a in acc.items():
        vec = np.array([np.median(a["r"][s]) if a["r"][s] else MISSING for s in SENSOR_IDS], float)
        out[i].append({"w": w, "t": w * WINDOW_S, "vec": vec, "n_sensors": len(a["r"]),
                       "pkts": a["pkts"], "data": a["data"], "kind": a["kind"]})
    for i in out:
        out[i].sort(key=lambda x: x["w"])
    return out


def norm(vec):
    """가장 센 값을 빼서 기기 송신 세기 차이를 지운다. USE_ABS면 가장 센 값 자체도 붙인다
    (벽 너머 신호가 전체적으로 약해지는 정보를 남기기 위해)."""
    v = vec - vec.max()
    return np.append(v, (vec.max() + 60) * ABS_WEIGHT) if USE_ABS else v


# ---------------- 1단계: 위치 판정 ----------------
class Locator:
    """k-NN 위치 판정. 센서가 하나 죽으면 남은 센서 열만으로 지문을 다시 맞춰 판정한다."""

    def __init__(self, k=K):
        self.k = k
        self.cache = {}

    def fit(self, calib_rows, labels):
        wins = windowize(calib_rows)
        raw, y = [], []
        for start, end, dev, zone in labels:
            for win in wins.get(dev, []):
                if win["t"] >= start and win["t"] + WINDOW_S <= end and win["n_sensors"] >= MIN_SENSORS:
                    raw.append(win["vec"])
                    y.append(zone)
        self.raw, self.y = np.array(raw), np.array(y)
        self.cache = {}
        return self

    def _model(self, cols):
        key = tuple(cols)
        if key not in self.cache:
            knn = KNeighborsClassifier(n_neighbors=self.k)
            knn.fit(np.array([norm(v[cols]) for v in self.raw]), self.y)
            self.cache[key] = knn
        return self.cache[key]

    def predict(self, vecs, cols=None):
        """→ 구역 이름 목록. 이웃 5개 중 3표 미만이면 '보류'. cols: 살아 있는 센서 열 번호."""
        if len(vecs) == 0:
            return []
        cols = list(range(len(SENSOR_IDS))) if cols is None else list(cols)
        idx = self._model(cols).kneighbors(np.array([norm(np.asarray(v)[cols]) for v in vecs]),
                                           return_distance=False)
        out = []
        for row in idx:
            zone, votes = Counter(self.y[row]).most_common(1)[0]
            out.append(zone if votes >= MIN_VOTES else HOLD)
        return out


def alive_cols(rows, now, span=30.0):
    """최근 span초 동안 한 줄이라도 보낸 센서의 열 번호 (센서 고장·케이블 빠짐 대응)."""
    seen = {r[1] for r in rows if now - span <= r[0] < now}
    cols = [i for i, sid in enumerate(SENSOR_IDS) if sid in seen]
    return cols if len(cols) >= MIN_SENSORS else list(range(len(SENSOR_IDS)))


def smooth(zones):
    """최근 3창 다수결. 2표 이상인 구역이 없으면 보류."""
    out = []
    for i in range(len(zones)):
        z, c = Counter(zones[max(0, i - SMOOTH + 1): i + 1]).most_common(1)[0]
        out.append(z if c >= 2 or i == 0 else HOLD)
    return out


def locate_all(wins, loc, cols=None):
    """창마다 zone(원판정), zone_s(다수결) 채우기. 센서 3대 미만 창은 판정 없음(None)."""
    for i, ws in wins.items():
        good = [w for w in ws if w["n_sensors"] >= MIN_SENSORS]
        for w, z in zip(good, loc.predict([w["vec"] for w in good], cols)):
            w["zone"] = z
        for w, z in zip(good, smooth([w["zone"] for w in good])):
            w["zone_s"] = z
        for w in ws:
            w.setdefault("zone", None)
            w.setdefault("zone_s", None)
    return wins


# ---------------- 신호 묶기 (MAC 교체 대응) ----------------
def signature(ws):
    """여러 창의 정규화 벡터 중앙값 = 그 신호의 '자리 지문'."""
    good = [norm(w["vec"]) for w in ws if w["n_sensors"] >= MIN_SENSORS]
    return np.median(good, axis=0) if len(good) >= 3 else None


def build_tracks(wins, baseline_ids=(), whitelist=()):
    """같은 자리에서 MAC만 바뀐 신호를 하나의 트랙으로 잇는다.
    조건: 같은 종류, 앞 신호가 끝나고 MERGE_GAP초 안에 새 신호 시작, 둘 다 교실 안,
          앞 신호 마지막 10창과 새 신호 처음 10창의 지문 거리가 MERGE_DIST 이하."""
    tracks = []
    order = sorted(wins, key=lambda i: wins[i][0]["t"])
    for i in order:
        ws = wins[i]
        base = i in baseline_ids or i in whitelist
        head = signature(ws[:10])
        first_in = any(w["zone_s"] in INSIDE + [CENTER] for w in ws[:10])
        target, best = None, MERGE_DIST
        if not base and head is not None and first_in:
            for tr in tracks:
                if tr["baseline"] or tr["kind"] != ws[0]["kind"] or tr["tail"] is None:
                    continue
                gap = ws[0]["t"] - tr["wins"][-1]["t"]
                if 0 < gap <= MERGE_GAP and tr["tail_in"]:
                    d = float(np.sqrt(np.mean((tr["tail"] - head) ** 2)))
                    if d <= best:
                        target, best = tr, d
        if target is None:
            target = {"ids": [], "wins": [], "kind": ws[0]["kind"], "baseline": base}
            tracks.append(target)
        target["ids"].append(i)
        target["wins"].extend(ws)
        target["wins"].sort(key=lambda w: w["t"])
        target["tail"] = signature(target["wins"][-10:])
        target["tail_in"] = any(w["zone_s"] in INSIDE + [CENTER] for w in target["wins"][-10:])
    return tracks


# ---------------- 2단계: 의심도 특징 ----------------
def features(tr, now, scale=1.0):
    """시험 시작(0)~now 까지의 창으로 특징 계산. scale: 압축 시연(실제 1초 = scale초)."""
    ws = [w for w in tr["wins"] if 0 <= w["t"] < now]
    if not ws:
        return None
    decided = [w["zone_s"] for w in ws if w["zone_s"] not in (None, HOLD)]
    inside = [z for z in decided if z in INSIDE or z == CENTER]
    hall = [z for z in decided if z == HALL]
    changes = sum(1 for a, b in zip(decided, decided[1:]) if a != b)
    times = [w["t"] for w in ws]
    reappear = sum(1 for a, b in zip(times, times[1:]) if (b - a) > REAPPEAR_GAP / scale)
    seen_s = len(ws) * WINDOW_S
    pk = sum(w["pkts"] for w in ws)
    main = Counter(z for z in inside if z in INSIDE).most_common(1)
    return {
        "seen_ratio": seen_s / max(now, WINDOW_S),
        "inside_ratio": len(inside) / max(len(inside) + len(hall), 1),
        "zone_changes": changes,
        "reappear": reappear,
        "pkt_per_sec": pk / seen_s,
        "data_frame_ratio": sum(w["data"] for w in ws) / max(pk, 1),
        "mean_rssi": float(np.mean([w["vec"].max() for w in ws])),
        "in_baseline": int(tr["baseline"]),
        "is_wifi": int(tr["kind"] == "WIFI"),
        # 잡힌 시간 × 교실 안 비율 (BLE처럼 판정 창이 드문 신호도 시간이 제대로 쌓이게)
        "inside_min": seen_s * (len(inside) / max(len(inside) + len(hall), 1)) * scale / 60,
        "near": main[0][0] if main else (CENTER if inside else (HALL if hall else HOLD)),
        "first_t": ws[0]["t"], "last_t": ws[-1]["t"],
    }


def level_rule(f):
    """규칙 기반 v0 (데이터가 쌓이면 RF로 교체)."""
    if f["in_baseline"]:
        return "낮음", "시험 전부터 있던 신호"
    if f["inside_ratio"] < INSIDE_RATIO:
        return "낮음", "대부분 교실 밖(통행)"
    if f["inside_min"] >= HIGH_MIN:
        return "높음", f"교실 안 {f['inside_min']:.0f}분 지속"
    if f["inside_min"] >= WATCH_MIN:
        return "관찰", f"교실 안 {f['inside_min']:.0f}분"
    return "낮음", "짧은 신호"


def level_from_proba(pr):
    """RF 3등급 확률 [낮음, 관찰, 높음] → 등급. 높음은 확률 PROB_HIGH 이상일 때만(잘못된 경보 억제)."""
    if pr[2] >= PROB_HIGH:
        return "높음"
    if pr[1] + pr[2] >= PROB_WATCH:
        return "관찰"
    return "낮음"


# ---------------- 한 번에 ----------------
def analyze(rows, loc, now, scale=1.0, whitelist=(), model=None):
    """now 시점까지의 rows → 대시보드 상태용 신호 목록."""
    rows = [r for r in rows if r[0] < now]
    wins = locate_all(windowize(rows), loc, alive_cols(rows, now))
    baseline_ids = {r[3] for r in rows if r[0] < 0}
    tracks = build_tracks(wins, baseline_ids, whitelist)
    out = []
    for tr in tracks:
        f = features(tr, now, scale)
        if f is None:
            continue
        if model is not None and not f["in_baseline"]:
            pr = model.predict_proba([[f[k] for k in RF_FEATURES]])[0]
            lvl = level_from_proba(pr)
            why = f"AI 판정 (높음 {pr[2]:.0%}) · 교실 안 {f['inside_min']:.0f}분"
        else:
            lvl, why = level_rule(f)
        out.append({"ids": tr["ids"], "kind": tr["kind"], "near": f["near"], "level": lvl, "why": why,
                    "minutes": round(f["inside_min"], 1), "inside": round(f["inside_ratio"], 2),
                    "first_t": f["first_t"], "last_t": f["last_t"], "baseline": bool(tr["baseline"]),
                    "f": {k: round(float(f[k]), 3) for k in FEATURES}})
    out.sort(key=lambda s: s["first_t"])
    return out

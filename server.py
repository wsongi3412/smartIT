"""감독관 태블릿 대시보드 서버 (표준 라이브러리만 사용).

① 리플레이(지금 바로, ESP32 없이):
    python server.py                         # 시뮬레이션 시험 1회를 빨리 감아 보여줌
    python server.py --replay data/exam_day2.csv --speed 100
② 실시간(ESP32 도착 후):
    python serial_reader.py data/live.csv    # 다른 터미널
    python server.py --live data/live.csv --calib data/calib_real.csv --scale 40
    → 태블릿 화면의 버튼으로 [기준 측정 시작] → [시험 시작] → [쉬는 시간으로] (순서대로만 눌림, 기준 측정 30초 이상)
      시험 시간은 화면의 [시험 바꾸기]에서 고른 값(고등 50분, 중학 45분, 수능 교시별 등)이 /control/start?min=N 으로 넘어옴
    --scale 40 : 시연용 압축 (실제 1초 = 시험 40초, 약 75초면 50분)
    → 시험 전 [보정] 탭: 구역마다 비콘을 놓고 [기록 시작]/[기록 끝] → [지도에 반영]
③ 판넬 캡처용 고정 화면:
    python server.py --at 35        # 시험 35분째 화면에서 멈춤 (50 이상이면 쉬는 시간 화면)

태블릿은 같은 핫스팟에 붙어서 http://<노트북 IP>:8000 으로 접속.
"""
import argparse
import json
import pickle
import os
import socket
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import sim
from config import seats_text, EXAM_MIN, SENSOR_IDS, INSIDE, CENTER, HALL, ALL_ZONES, MIN_SENSORS, hash_id
from pipeline import Locator, analyze, load_rows, load_labels, windowize, WINDOW_S

BASE_MIN_S = 30    # 기준 측정 최소 30초 (이보다 짧으면 [시험 시작] 잠김)
BASE_GOOD_S = 60   # 1분 이상 권장 (BLE 기기는 광고 간격이 길어 늦게 잡힘)

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL_ORDER = {"높음": 0, "관찰": 1, "낮음": 2}


class State:
    def __init__(self, a):
        self.a = a
        self.lock = threading.Lock()
        self.numbers = {}
        self.snapshot = {"phase": "준비 중", "signals": []}
        if a.calib:
            self.base_calib = (load_rows(a.calib), load_labels(a.calib.replace(".csv", "_labels.csv")))
        else:
            self.base_calib = sim.make_calib(1)
        self.loc = Locator().fit(*self.base_calib)
        # 보정 모드: 현장에서 추가한 신호 지도 지점 (실시간 파일과 같은 폴더의 *_labels.csv 에 저장)
        self.calib_labels, self.calib_cur, self.calib_applied = [], None, 0
        if a.live:
            self.calib_path = a.live.replace(".csv", "_labels.csv")
            if os.path.exists(self.calib_path):
                self.calib_labels = load_labels(self.calib_path)
        self.model = pickle.load(open(a.model, "rb")) if a.model else None
        self.whitelist = set()
        wl = os.path.join(HERE, "whitelist.txt")
        if os.path.exists(wl):   # 팀 노트북·핫스팟·태블릿 MAC (한 줄에 하나)
            self.whitelist = {hash_id(x.strip()) for x in open(wl, encoding="utf-8") if x.strip() and not x.startswith("#")}
        self.exam_min = EXAM_MIN          # 실시간: 화면에서 고른 시험 시간(분). [시험 시작] 때 정해짐
        if a.live:
            self.phase, self.start, self.end_at = "대기", None, None
        else:
            self.rows = load_rows(a.replay) if a.replay else sim.make_exam(a.seed, variant=a.variant)[0]
            self.t0 = time.time()

    # ---- 실시간 모드 제어 ----
    def control(self, cmd, minutes=None):
        with self.lock:
            now = time.time()
            if cmd == "baseline":
                self.phase, self.start, self.end_at = "기준선", None, None
                self.base_from = now
            elif cmd == "start":
                if self.phase != "기준선" or now - self.base_from < BASE_MIN_S:   # ① 기준 측정 30초 이상 먼저
                    return
                if minutes and 10 <= minutes <= 180:      # 화면에서 고른 시험 시간 (수능 교시, 중학교 45분 등)
                    self.exam_min = minutes
                self.phase, self.start = "시험 중", now
            elif cmd == "end":
                if self.start is not None and self.end_at is None:
                    self.phase, self.end_at = "쉬는 시간", now
                    self.save_recording()
            elif cmd == "reset":
                self.phase, self.start, self.end_at = "대기", None, None
                self.base_from = now
                self.numbers = {}

    def save_recording(self):
        """실시간 시험이 끝나면 기록을 data/exams/ 에 저장 → run_all.py 가 그대로 읽는다.
        exam_시각.csv (t=시험 시작 기준 초), _meta.json (scale, end), _truth.csv (정답 양식, 사람이 채움)"""
        try:
            rows = self._live_rows()
            end = self.end_at - self.start
            folder = os.path.join(HERE, "data", "exams")
            os.makedirs(folder, exist_ok=True)
            base = os.path.join(folder, time.strftime("exam_%Y%m%d_%H%M%S"))
            with open(base + ".csv", "w", encoding="utf-8") as f:
                f.write("t,sensor,kind,id,rssi,frame,n\n")
                for r in rows:
                    if r[0] <= end:
                        f.write(",".join(str(x) for x in (round(r[0], 3),) + tuple(r[1:])) + "\n")
            with open(base + "_meta.json", "w", encoding="utf-8") as f:
                json.dump({"scale": self.a.scale, "end": round(end, 3)}, f)
            new_ids = sorted({r[3] for r in rows if 0 <= r[0] <= end} - {r[3] for r in rows if r[0] < 0})
            with open(base + "_truth.csv", "w", encoding="utf-8") as f:
                f.write("id,level,note\n# level 칸에 높음/관찰/낮음, note 에 무엇이었는지 적기 (숨긴 기기 MAC은 원래 주소로 적어도 됨)\n")
                for i in new_ids:
                    f.write(f"{i},,\n")
            print(f"[기록 저장] {base}.csv  (정답 양식: _truth.csv 채우기)")
        except Exception as e:
            print(f"[기록 저장 실패] {e}")

    def _live_rows(self):
        rows = []
        if not os.path.exists(self.a.live):
            return rows
        base_from = getattr(self, "base_from", 0)
        origin = self.start or time.time()
        self.last_seen = {}
        with open(self.a.live, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                p = line.rstrip().split(",")
                if len(p) != 7:
                    continue
                t = float(p[0])
                self.last_seen[p[1]] = t
                if t < base_from:
                    continue
                rows.append((t - origin, p[1], p[2], p[3], int(p[4]), p[5], int(p[6])))
        return rows

    # ---- 보정 모드 ----
    def _raw_live_rows(self, since=0.0):
        rows = []
        if not os.path.exists(self.a.live):
            return rows
        with open(self.a.live, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                p = line.rstrip().split(",")
                if len(p) == 7 and float(p[0]) >= since:
                    rows.append((float(p[0]), p[1], p[2], p[3], int(p[4]), p[5], int(p[6])))
        return rows

    def calib_candidates(self, span=8.0):
        """최근 span초 동안 잡힌 신호 중 가장 센 것부터 (비콘을 놓은 자리 바로 옆 센서가 크게 들음)"""
        now = time.time()
        best = {}
        for t, sen, kind, i, v, fr, n in self._raw_live_rows(now - span):
            b = best.setdefault(i, {"id": i, "kind": kind, "max": -999, "sensors": set(), "n": 0})
            b["max"] = max(b["max"], v)
            b["sensors"].add(sen)
            b["n"] += n
        out = sorted(best.values(), key=lambda x: -x["max"])[:40]   # 화면은 위 8개 + 직접 입력한 주소
        return [{**x, "sensors": len(x["sensors"])} for x in out]

    def calib_windows(self, t0, t1, dev):
        wins = windowize([r for r in self._raw_live_rows(t0) if r[0] <= t1 and r[3] == dev])
        return sum(1 for w in wins.get(dev, []) if w["n_sensors"] >= MIN_SENSORS)

    def calib(self, cmd, body):
        with self.lock:
            if self.a.live is None:
                return {"ok": False, "msg": "보정은 실시간 모드(--live)에서만 할 수 있어요"}
            if self.phase not in ("대기", "기준선"):
                return {"ok": False, "msg": "보정은 시험 전에만 할 수 있어요 ([초기화] 후 다시)"}
            if cmd == "start":
                if body.get("zone") not in ALL_ZONES or not body.get("id"):
                    return {"ok": False, "msg": "구역과 비콘 신호를 고르세요"}
                self.calib_cur = {"t0": time.time(), "zone": body["zone"], "id": body["id"]}
                return {"ok": True, "msg": f"{body['zone']} 기록 중… 6초 이상 지나면 [기록 끝]"}
            if cmd == "stop":
                c = self.calib_cur
                if not c:
                    return {"ok": False, "msg": "기록 중인 지점이 없어요"}
                t1 = time.time()
                self.calib_cur = None
                n = self.calib_windows(c["t0"], t1, c["id"])
                if n < 2:
                    return {"ok": False, "msg": f"쓸 수 있는 2초 창이 {n}개뿐이에요. 비콘이 켜져 있는지 보고 다시 기록하세요"}
                self.calib_labels.append((c["t0"], t1, c["id"], c["zone"]))
                with open(self.calib_path, "w", encoding="utf-8") as f:
                    f.write("start,end,id,zone\n")
                    for l in self.calib_labels:
                        f.write(f"{l[0]:.3f},{l[1]:.3f},{l[2]},{l[3]}\n")
                return {"ok": True, "msg": f"{c['zone']} 기록 완료 (2초 창 {n}개)"}
            if cmd == "undo":
                if self.calib_labels:
                    self.calib_labels.pop()
                return {"ok": True, "msg": "마지막 지점을 지웠어요"}
            if cmd == "apply":
                if not self.calib_labels:
                    return {"ok": False, "msg": "추가한 지점이 없어요"}
                rows = self._raw_live_rows(min(l[0] for l in self.calib_labels) - 1)
                if self.a.calib:          # 미리 잰 신호 지도(--calib) + 현장 보충
                    b_rows, b_labels = self.base_calib
                    self.loc = Locator().fit(list(b_rows) + rows, list(b_labels) + self.calib_labels)
                else:                     # 신호 지도 파일 없음 = 처음 온 강의실 → 가짜(시뮬레이션) 지도는 버리고 현장 측정만 씀
                    # 가운데는 화면 배치가 짝수(예: 6x6)면 없으므로 빼고 확인
                    missing = [z for z in ALL_ZONES if z != CENTER and not any(l[3] == z for l in self.calib_labels)]
                    if missing:
                        return {"ok": False, "msg": f"아직 안 잰 구역: {', '.join(missing)}. 네 모서리와 복도(배치가 홀수면 가운데도)를 2자리 이상 재 주세요"}
                    self.loc = Locator().fit(rows, list(self.calib_labels))
                    self.field_only = True
                    self.calib_applied = len(self.calib_labels)
                    few = [z for z in ALL_ZONES if (z != CENTER or (self.loc.y == z).any()) and int((self.loc.y == z).sum()) < 5]
                    if few:   # k-NN은 이웃 5개 중 3표가 필요 → 구역마다 지문 5개 이상이어야 판정이 안정적
                        return {"ok": True, "msg": f"반영했어요 (지문 {len(self.loc.y)}개). 다만 지문이 적은 구역: {', '.join(few)} → 그 구역에 자리를 더 재고 다시 [지도에 반영]"}
                    return {"ok": True, "msg": f"현장 측정만으로 신호 지도를 만들었어요 (지문 {len(self.loc.y)}개)"}
                self.calib_applied = len(self.calib_labels)
                return {"ok": True, "msg": f"신호 지도에 {len(self.calib_labels)}개 지점을 반영했어요 (지문 {len(self.loc.y)}개)"}
            return {"ok": False, "msg": "알 수 없는 명령"}

    def calib_state(self):
        per = {z: 0 for z in ALL_ZONES}
        for l in self.calib_labels:
            per[l[3]] += 1
        return {"points": per, "total": len(self.calib_labels), "applied": self.calib_applied,
                "recording": self.calib_cur and {"zone": self.calib_cur["zone"],
                                                 "sec": round(time.time() - self.calib_cur["t0"], 1)}}

    def base_state(self, rows, sensor_age):
        """① 기준 측정 진행 상황: 몇 초째인지, 신호 몇 개를 '원래 있던 신호'로 기록했는지, 센서 몇 대가 살아 있는지."""
        ok = sum(1 for v in sensor_age.values() if v is not None and v < 10)
        if self.phase == "기준선":
            return {"sec": round(time.time() - self.base_from), "ids": len({r[3] for r in rows}),
                    "sensors": ok, "need": BASE_MIN_S, "good": BASE_GOOD_S}
        return {"sec": None, "ids": None, "sensors": ok, "need": BASE_MIN_S, "good": BASE_GOOD_S}

    def tick(self):
        a = self.a
        if a.live:
            rows = self._live_rows()
            if self.phase in ("대기", "기준선"):
                now, phase = 0.0, self.phase
            else:
                now = ((self.end_at or time.time()) - self.start)
                if self.end_at is None and now * a.scale >= self.exam_min * 60:   # 시험 시간이 다 되면 자동으로 쉬는 시간
                    self.phase, self.end_at = "쉬는 시간", self.start + self.exam_min * 60 / a.scale
                    self.save_recording()
                    now = self.end_at - self.start
                phase = self.phase
            scale = a.scale
            exam_min = now * scale / 60
            seen = getattr(self, "last_seen", {})
            sensor_age = {s: (round(time.time() - seen[s], 1) if s in seen else None) for s in SENSOR_IDS}
        else:
            elapsed = (time.time() - self.t0) * a.speed - 120      # 기준선 2분부터 시작
            if a.at is not None:                                     # 판넬 캡처용 고정 화면
                elapsed = a.at * 60
            cycle = EXAM_MIN * 60 + 120 + a.break_s * a.speed
            elapsed = (elapsed + 120) % cycle - 120 if (a.loop and a.at is None) else elapsed
            if elapsed < 0:
                phase, now = "기준선", 0.0
            elif elapsed < EXAM_MIN * 60:
                phase, now = "시험 중", elapsed
            else:
                phase, now = "쉬는 시간", EXAM_MIN * 60.0
            rows, scale, exam_min = self.rows, 1.0, now / 60
            sensor_age = {s: 0.5 for s in SENSOR_IDS}
        sig = analyze(rows, self.loc, now=max(now, 0.001), scale=scale, whitelist=self.whitelist,
                      model=self.model) if now > 0 else []
        if phase in ("대기", "기준선"):
            self.numbers = {}
        show = []
        for s in sig:
            if s["baseline"]:
                continue
            key = s["ids"][0]
            if key not in self.numbers:
                self.numbers[key] = len(self.numbers) + 1
            show.append({"no": self.numbers[key], "kind": s["kind"], "near": s["near"], "seats": seats_text(s["near"]), "level": s["level"],
                         "why": s["why"], "minutes": s["minutes"], "inside": s["inside"],
                         "macs": len(s["ids"]), "active": (now - s["last_t"]) < 10})
        show.sort(key=lambda x: (LEVEL_ORDER[x["level"]], x["no"]))
        heat = {z: 0.0 for z in INSIDE + [CENTER, HALL]}      # 구역별 누적 분 (시험 시작 후 새 신호만)
        for x in show:
            if x["near"] in heat:
                heat[x["near"]] += x["minutes"] if x["near"] != HALL else 0
        for x in show:
            if x["near"] == HALL:
                heat[HALL] += 1
        snap = {"mode": "live" if a.live else "replay", "phase": phase,
                "map": ("현장 측정" if getattr(self, "field_only", False) else
                        ("측정 파일" + (" + 현장 보충" if self.calib_applied else "") if a.calib else "가짜(시뮬레이션) 지도 — 위치 틀림, 보정 필요")) if a.live else "가짜 시험", "exam_min": round(exam_min, 1),
                "exam_total": self.exam_min if a.live else EXAM_MIN, "signals": show,
                "baseline_count": sum(1 for s in sig if s["baseline"]),
                "sensor_age": sensor_age, "updated": time.strftime("%H:%M:%S"),
                "heat": {k: round(v, 1) for k, v in heat.items()},
                "calib": self.calib_state() if a.live else None,
                "base": self.base_state(rows, sensor_age) if a.live else None}
        with self.lock:
            self.snapshot = snap

    def loop(self):
        while True:
            try:
                self.tick()
            except Exception as e:  # 시연 중 서버가 죽지 않게
                with self.lock:
                    self.snapshot = {**self.snapshot, "error": str(e)}
            time.sleep(1)


def make_handler(state):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/state"):
                with state.lock:
                    body = json.dumps(state.snapshot, ensure_ascii=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            elif self.path.startswith("/calib/candidates"):
                body = json.dumps(state.calib_candidates() if state.a.live else [], ensure_ascii=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            elif self.path in ("/", "/index.html"):
                with open(os.path.join(HERE, "dashboard.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path.startswith("/calib/"):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    body = {}
                res = state.calib(self.path.rsplit("/", 1)[1], body)
                self._send(200, json.dumps(res, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            elif self.path.startswith("/control/") and state.a.live:
                u = urlparse(self.path)
                q = parse_qs(u.query)
                try:
                    minutes = int(q["min"][0]) if "min" in q else None
                except ValueError:
                    minutes = None
                state.control(u.path.rsplit("/", 1)[1], minutes)
                state.tick()
                self._send(200, b"ok", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")
    return H


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay")
    ap.add_argument("--live")
    ap.add_argument("--calib")
    ap.add_argument("--speed", type=float, default=100, help="리플레이 배속 (100 = 50분을 30초에)")
    ap.add_argument("--break-s", type=float, default=8, help="리플레이: 쉬는 시간 화면 유지(초)")
    ap.add_argument("--loop", action="store_true", default=True)
    ap.add_argument("--scale", type=float, default=1.0, help="실시간 압축 시연 배율")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--variant", choices=["cam", "ear", "glasses"], default="cam")
    ap.add_argument("--model", help="train_rf.py 로 만든 data/rf.pkl (없으면 규칙 기반)")
    ap.add_argument("--at", type=float, help="리플레이를 이 시험 분에 고정 (판넬 캡처용, 50 이상 = 쉬는 시간)")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    st = State(a)
    threading.Thread(target=st.loop, daemon=True).start()
    print(f"대시보드: http://{lan_ip()}:{a.port}  (이 노트북에서는 http://localhost:{a.port})")
    ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(st)).serve_forever()

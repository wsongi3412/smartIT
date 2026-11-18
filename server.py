"""감독관 태블릿 대시보드 서버 (표준 라이브러리만 사용).

① 리플레이(지금 바로, ESP32 없이):
    python server.py                         # 시뮬레이션 시험 1회를 빨리 감아 보여줌
    python server.py --replay data/exam_day2.csv --speed 100
② 실시간(ESP32 도착 후):
    python serial_reader.py data/live.csv    # 다른 터미널
    python server.py --live data/live.csv --calib data/calib_real.csv --scale 40
    → 태블릿 화면의 버튼으로 [기준선] → [시험 시작] → [쉬는 시간]
    --scale 40 : 시연용 압축 (실제 1초 = 시험 40초, 약 75초면 50분)

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

import sim
from config import EXAM_MIN, SENSOR_IDS, hash_id
from pipeline import Locator, analyze, load_rows, load_labels

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL_ORDER = {"높음": 0, "관찰": 1, "낮음": 2}


class State:
    def __init__(self, a):
        self.a = a
        self.lock = threading.Lock()
        self.numbers = {}
        self.snapshot = {"phase": "준비 중", "signals": []}
        if a.calib:
            self.loc = Locator().fit(load_rows(a.calib), load_labels(a.calib.replace(".csv", "_labels.csv")))
        else:
            self.loc = Locator().fit(*sim.make_calib(1))
        self.model = pickle.load(open(a.model, "rb")) if a.model else None
        self.whitelist = set()
        wl = os.path.join(HERE, "whitelist.txt")
        if os.path.exists(wl):   # 팀 노트북·핫스팟·태블릿 MAC (한 줄에 하나)
            self.whitelist = {hash_id(x.strip()) for x in open(wl) if x.strip() and not x.startswith("#")}
        if a.live:
            self.phase, self.start, self.end_at = "대기", None, None
        else:
            self.rows = load_rows(a.replay) if a.replay else sim.make_exam(a.seed, variant=a.variant)[0]
            self.t0 = time.time()

    # ---- 실시간 모드 제어 ----
    def control(self, cmd):
        with self.lock:
            now = time.time()
            if cmd == "baseline":
                self.phase, self.start, self.end_at = "기준선", None, None
                self.base_from = now
            elif cmd == "start":
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
            with open(base + ".csv", "w") as f:
                f.write("t,sensor,kind,id,rssi,frame,n\n")
                for r in rows:
                    if r[0] <= end:
                        f.write(",".join(str(x) for x in (round(r[0], 3),) + tuple(r[1:])) + "\n")
            with open(base + "_meta.json", "w") as f:
                json.dump({"scale": self.a.scale, "end": round(end, 3)}, f)
            new_ids = sorted({r[3] for r in rows if 0 <= r[0] <= end} - {r[3] for r in rows if r[0] < 0})
            with open(base + "_truth.csv", "w") as f:
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
        with open(self.a.live) as f:
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

    def tick(self):
        a = self.a
        if a.live:
            rows = self._live_rows()
            if self.phase in ("대기", "기준선"):
                now, phase = 0.0, self.phase
            else:
                now = ((self.end_at or time.time()) - self.start)
                if self.end_at is None and now * a.scale >= EXAM_MIN * 60:   # 50분 되면 자동으로 쉬는 시간
                    self.phase, self.end_at = "쉬는 시간", self.start + EXAM_MIN * 60 / a.scale
                    self.save_recording()
                    now = self.end_at - self.start
                phase = self.phase
            scale = a.scale
            exam_min = now * scale / 60
            seen = getattr(self, "last_seen", {})
            sensor_age = {s: (round(time.time() - seen[s], 1) if s in seen else None) for s in SENSOR_IDS}
        else:
            elapsed = (time.time() - self.t0) * a.speed - 120      # 기준선 2분부터 시작
            cycle = EXAM_MIN * 60 + 120 + a.break_s * a.speed
            elapsed = (elapsed + 120) % cycle - 120 if a.loop else elapsed
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
            show.append({"no": self.numbers[key], "kind": s["kind"], "near": s["near"], "level": s["level"],
                         "why": s["why"], "minutes": s["minutes"], "inside": s["inside"],
                         "macs": len(s["ids"]), "active": (now - s["last_t"]) < 10})
        show.sort(key=lambda x: (LEVEL_ORDER[x["level"]], x["no"]))
        snap = {"mode": "live" if a.live else "replay", "phase": phase, "exam_min": round(exam_min, 1),
                "exam_total": EXAM_MIN, "signals": show,
                "baseline_count": sum(1 for s in sig if s["baseline"]),
                "sensor_age": sensor_age, "updated": time.strftime("%H:%M:%S")}
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
            elif self.path in ("/", "/index.html"):
                with open(os.path.join(HERE, "dashboard.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path.startswith("/control/") and state.a.live:
                state.control(self.path.rsplit("/", 1)[1])
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
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    st = State(a)
    threading.Thread(target=st.loop, daemon=True).start()
    print(f"대시보드: http://{lan_ip()}:{a.port}  (이 노트북에서는 http://localhost:{a.port})")
    ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(st)).serve_forever()

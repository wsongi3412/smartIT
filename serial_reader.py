"""ESP32 센서 → (무선 ESP-NOW → 수신기 ESP32 1대, 또는 센서 USB 직접) → 이 스크립트 → CSV.

11-24: 센서는 보조배터리로 켜고 무선으로 보낸다. 노트북에는 수신기(firmware/esp32_gateway) 1대만 꽂는다.
       수신기가 센서 USB와 똑같은 줄을 출력하므로 이 스크립트는 그대로. '#' 상태 줄은 화면에만 보여 준다.

ESP32 한 줄 출력:  A,BLE,aa:bb:cc:dd:ee:ff,-58,A,1     (센서,종류,주소,세기,프레임,패킷수)
여기서 시각(t, 유닉스 초)을 붙이고 주소를 해시로 바꿔 저장한다. 패킷 내용은 받지도 저장하지도 않는다.

준비:  pip install pyserial
실행:  python serial_reader.py data/live.csv
       python serial_reader.py data/live.csv --ports /dev/cu.usbserial-0001 /dev/cu.usbserial-0002
"""
import argparse
import glob
import os
import sys
import threading
import time
from collections import Counter

from config import SENSOR_IDS, hash_id

lock = threading.Lock()
counts = Counter()


def find_ports():
    pats = ["/dev/cu.usbserial*", "/dev/cu.SLAB_USBtoUART*", "/dev/cu.wchusbserial*", "/dev/ttyUSB*", "COM*"]
    return sorted({p for pat in pats for p in glob.glob(pat)})


def read_port(port, out, baud):
    import serial
    while True:
        try:
            with serial.Serial(port, baud, timeout=1) as ser:
                print(f"[연결] {port}")
                while True:
                    raw = ser.readline().decode(errors="ignore").strip()
                    if raw.startswith("# 10s") or raw.startswith("# gateway"):
                        print(f"  [수신기] {raw[2:]}")
                    p = raw.split(",")
                    if len(p) != 6 or p[0] not in SENSOR_IDS or p[1] not in ("BLE", "WIFI"):
                        continue          # 부팅 메시지 등 무시
                    try:
                        rssi, n = int(p[3]), int(p[5])
                    except ValueError:
                        continue
                    line = f"{time.time():.3f},{p[0]},{p[1]},{hash_id(p[2])},{rssi},{p[4]},{n}\n"
                    with lock:
                        out.write(line)
                        counts[p[0]] += 1
        except Exception as e:   # 케이블 빠짐 등 → 2초 뒤 재연결
            print(f"[끊김] {port}: {e}")
            time.sleep(2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--ports", nargs="*")
    ap.add_argument("--baud", type=int, default=460800)
    a = ap.parse_args()
    ports = a.ports or find_ports()
    if not ports:
        sys.exit("ESP32 포트를 못 찾음. USB 연결과 드라이버(CP210x/CH340)를 확인하세요.")
    new = not os.path.exists(a.out)
    out = open(a.out, "a", buffering=1)
    if new:
        out.write("t,sensor,kind,id,rssi,frame,n\n")
    for p in ports:
        threading.Thread(target=read_port, args=(p, out, a.baud), daemon=True).start()
    print(f"기록 중 → {a.out}  (Ctrl+C로 종료)")
    while True:
        time.sleep(5)
        with lock:
            print("  최근 5초 줄 수:", {s: counts[s] for s in SENSOR_IDS})
            counts.clear()

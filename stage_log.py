"""연출 기록(정답 라벨) 도우미 — 보정·데이터 수집 때 serial_reader.py 와 함께 돌린다.

사용:
    python stage_log.py data/calib_day1.csv --id aa:bb:cc:dd:ee:ff
    → 구역 번호를 입력하고 Enter = 그 자리에 기기를 둔 '시작', 다시 Enter = '끝'
      (기기를 옮기는 동안의 신호는 라벨에서 빠짐)

결과: data/calib_day1_labels.csv  (start,end,id,zone) — pipeline.Locator.fit 이 읽는 형식
보정용 기기 MAC은 serial_reader 가 쓰는 것과 같은 해시로 저장된다.
"""
import argparse
import csv
import os
import time

from config import ALL_ZONES, hash_id

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("calib_csv", help="serial_reader 가 기록 중인 CSV")
    ap.add_argument("--id", required=True, help="보정에 쓰는 기기의 MAC (원래 주소)")
    a = ap.parse_args()
    path = a.calib_csv.replace(".csv", "_labels.csv")
    new = not os.path.exists(path)
    dev = hash_id(a.id)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["start", "end", "id", "zone"])
        menu = "  ".join(f"{i}:{z}" for i, z in enumerate(ALL_ZONES, 1))
        n = 0
        while True:
            s = input(f"\n구역 번호 ({menu}, q=끝) > ").strip()
            if s == "q":
                break
            if not s.isdigit() or not 1 <= int(s) <= len(ALL_ZONES):
                continue
            zone = ALL_ZONES[int(s) - 1]
            input(f"  [{zone}] 기기를 놓고 손을 뗀 뒤 Enter = 시작")
            t0 = time.time()
            input("  ...수집 중 (6초 이상 권장). Enter = 끝")
            t1 = time.time()
            w.writerow([f"{t0:.3f}", f"{t1:.3f}", dev, zone])
            f.flush()
            n += 1
            print(f"  기록됨: {zone} {t1 - t0:.0f}초  (총 {n}개 지점)")
    print(f"라벨 → {path}")

"""규칙 vs 랜덤포레스트 비교 + 판넬용 그림 (11-22).

    python3 experiments/compare.py            → docs/panel/ 에 그림 2장 + 비교표.md

  위치_혼동행렬.png       실제 위치 × AI 판정 위치 (1단계, k-NN)
  의심도_규칙_vs_RF.png   정답 등급 × 판정 등급, 규칙과 RF를 나란히 (2단계)
  비교표.md               보통 시험 15회 + 어려운 경우 4종×10회 성적표

⚠️ 지금 숫자는 전부 가짜 데이터(시뮬레이션). 그림 아래에 그렇게 적혀 나간다.
   실측 데이터가 생기면 run_all.py 와 같은 입력으로 바꿔 다시 그린다.
"""
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sim  # noqa: E402
from config import ALL_ZONES, HOLD, EXAM_MIN  # noqa: E402
from pipeline import Locator, analyze  # noqa: E402
from run_all import demo_exams, train_rf, truth_of, zone_score, LEVELS  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "panel")
HARD_RUNS = 10

# 색: 한 가지 파랑 (옅음 → 진함). 판넬 인쇄에서도 0과 큰 값이 구분되게.
BLUE = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
INK, MUTED, GRID = "#16202a", "#5b6670", "#ffffff"


def hard_exams():
    out = []
    for case in sim.HARD_CASES:
        for i in range(HARD_RUNS):
            rows, truth = sim.make_hard(500 + i, case)
            out.append((f"hard_{case}_{i}", rows, {k: lv for k, (lv, _) in truth.items()}, 1.0, EXAM_MIN * 60.0, case))
    return out


def judge(loc, exams, model):
    """→ [(경우, 정답, 판정, 벽근처)] 기준선 신호 제외, 시험 끝 시점."""
    res = []
    for ex in exams:
        name, rows, truth, scale, end = ex[:5]
        case = ex[5] if len(ex) > 5 else "보통"
        for s in analyze(rows, loc, now=end, scale=scale, model=model):
            if not s["baseline"]:
                res.append((case, truth_of(s, truth), s["level"], s.get("wall", False)))
    return res


def score(res):
    hi = [r for r in res if r[1] == "높음"]
    lo = [r for r in res if r[1] == "낮음"]
    return {
        "hi": (sum(r[2] == "높음" for r in hi), len(hi)),
        "hi_or_watch": (sum(r[2] in ("높음", "관찰") for r in hi), len(hi)),
        "false_hi": sum(r[2] == "높음" for r in lo),
        "false_watch": sum(r[2] == "관찰" for r in lo),
    }


def setup_font(plt):
    from matplotlib import font_manager
    have = {f.name for f in font_manager.fontManager.ttflist}
    kr = [n for n in ("Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic", "NanumGothic", "Noto Sans CJK KR") if n in have]
    plt.rcParams["font.family"] = kr[:1] or ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def draw_matrix(ax, m, rows, cols, title, cmap, diag_cols=None):
    frac = m / np.maximum(m.sum(1, keepdims=True), 1)
    ax.imshow(frac, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(cols)), cols, fontsize=11)
    ax.set_yticks(range(len(rows)), [f"{r}  ({int(m[i].sum())})" for i, r in enumerate(rows)], fontsize=11)
    ax.tick_params(length=0, colors=INK)
    ax.xaxis.set_ticks_position("top")
    ax.xaxis.set_label_position("top")
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks(np.arange(-.5, len(cols)), minor=True)
    ax.set_yticks(np.arange(-.5, len(rows)), minor=True)
    ax.grid(which="minor", color=GRID, linewidth=2)
    ax.tick_params(which="minor", length=0)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if not m[i, j]:
                continue
            on_diag = diag_cols is not None and diag_cols[j] == rows[i]
            ax.text(j, i, f"{frac[i, j]:.0%}", ha="center", va="center", fontsize=12 if on_diag else 10,
                    fontweight="bold" if on_diag else "normal",
                    color="white" if frac[i, j] > 0.5 else INK)
    ax.set_title(title, fontsize=13, color=INK, pad=34, loc="left", fontweight="bold")


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    setup_font(plt)
    cmap = LinearSegmentedColormap.from_list("one_blue", BLUE)
    os.makedirs(OUT, exist_ok=True)

    print("위치 AI 학습 (신호 지도 1일차) → 2일차로 채점")
    loc = Locator().fit(*sim.make_calib(1))
    z = zone_score(loc, *sim.make_calib(2))

    # ---- 그림 1: 위치 혼동 행렬 ----
    cols = ALL_ZONES + [HOLD]
    m = np.zeros((len(ALL_ZONES), len(cols)), int)
    for t, p in z["pairs"]:
        m[ALL_ZONES.index(t), cols.index(p)] += 1
    fig, ax = plt.subplots(figsize=(8, 5.6), dpi=200)
    draw_matrix(ax, m, ALL_ZONES, cols, "위치 AI(k-NN): 실제 자리 → AI가 판정한 자리", cmap, diag_cols=cols)
    ax.set_ylabel("실제 자리 (창 개수)", fontsize=11, color=MUTED)
    fig.text(0.01, 0.015, f"구역 정확도 {z['acc']:.0%} (보류 제외) · 복도→교실 안 잘못 판정 {z['hall_in']:.0%} · "
             "가짜 데이터(시뮬레이션), 실측 후 교체", fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(os.path.join(OUT, "위치_혼동행렬.png"))
    plt.close(fig)

    # ---- 의심도: 규칙 vs RF ----
    print("의심도 AI(RF) 학습: 시험 1일차 20회")
    model, info = train_rf(loc, demo_exams(range(1000, 1020)))
    normal = demo_exams(range(2000, 2015))
    hard = hard_exams()
    print(f"채점: 보통 시험 {len(normal)}회 + 어려운 경우 {len(hard)}회")
    R = {"규칙": judge(loc, normal, None) + judge(loc, hard, None),
         "RF": judge(loc, normal, model) + judge(loc, hard, model)}

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), dpi=200)
    for ax, (name, res) in zip(axes, R.items()):
        mm = np.zeros((3, 3), int)
        for _, t, p, _ in res:
            mm[LEVELS[::-1].index(t), LEVELS[::-1].index(p)] += 1
        label = "규칙 (사람이 정한 기준)" if name == "규칙" else "랜덤포레스트 (데이터로 학습)"
        draw_matrix(ax, mm, LEVELS[::-1], LEVELS[::-1], label, cmap, diag_cols=LEVELS[::-1])
    axes[0].set_ylabel("정답 등급 (신호 개수)", fontsize=11, color=MUTED)
    fig.text(0.01, 0.02, f"보통 시험 {len(normal)}회 + 어려운 경우 {len(hard)}회, 시험 끝 시점 · 가로 = AI 판정 · "
             "가짜 데이터(시뮬레이션), 실측 후 교체", fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(os.path.join(OUT, "의심도_규칙_vs_RF.png"))
    plt.close(fig)

    # ---- 비교표 ----
    def f(a):
        return f"{a[0]}/{a[1]}" if a[1] else "-"

    L = ["# 규칙 vs 랜덤포레스트 비교표", "",
         "> ⚠️ 가짜 데이터(시뮬레이션) 결과. 코드가 맞게 도는지 확인용이며 판넬에는 실측으로 바꿔 넣는다.",
         f"> 만든 명령: `python3 experiments/compare.py` · RF 중요 특징: {info}", "",
         "## 한눈에", "", "| 지표 | 목표 | 규칙 | RF |", "|---|---|---|---|"]
    S = {n: score(r) for n, r in R.items()}
    L += [f"| 숨긴 기기 → 높음 | 90% 이상 | {f(S['규칙']['hi'])} | {f(S['RF']['hi'])} |",
          f"| 숨긴 기기 → 관찰 이상 (놓치지 않음) | 100% | {f(S['규칙']['hi_or_watch'])} | {f(S['RF']['hi_or_watch'])} |",
          f"| 잘못된 경보 (낮음인데 높음) | 0회 | {S['규칙']['false_hi']}회 | {S['RF']['false_hi']}회 |",
          f"| 낮음인데 관찰 (가벼운 헛걸음) | 적을수록 | {S['규칙']['false_watch']}회 | {S['RF']['false_watch']}회 |",
          "", "## 경우별", "", "| 경우 | 규칙: 높음 / 관찰 이상 / 잘못된 경보 | RF: 높음 / 관찰 이상 / 잘못된 경보 |", "|---|---|---|"]
    names = {"보통": "보통 시험 (카메라·이어폰·AI 안경 중 1개)", **sim.HARD_CASES}
    for case, desc in names.items():
        cells = []
        for n in ("규칙", "RF"):
            s = score([r for r in R[n] if r[0] == case])
            if s["hi"][1]:
                cells.append(f"{f(s['hi'])} / {f(s['hi_or_watch'])} / {s['false_hi']}회")
            else:   # 숨긴 기기가 없는 경우: 오래 있던 사람이 '낮음'으로 남았는지
                lo = [r for r in R[n] if r[0] == case and r[1] == "낮음"]
                cells.append(f"(숨긴 기기 없음) 낮음 유지 {sum(r[2] == '낮음' for r in lo)}/{len(lo)} / {s['false_hi']}회")
        L.append(f"| {desc} | {cells[0]} | {cells[1]} |")
    walls = {n: sum(1 for r in R[n] if r[3]) for n in R}
    L += ["", f"- '벽 근처' 조건(교실 안 비율 25~50% + 15분 이상)에 걸린 신호: {walls['규칙']}개. "
          "규칙은 이것을 '관찰 (벽 근처)'로 판정하고, RF가 '낮음'이라 해도 '관찰'로 올린다.",
          "- 숨긴 기기 개수가 시험 횟수보다 많은 이유: AI 안경은 MAC이 바뀌어 이어 붙지 못한 조각을 각각 센다. "
          "짧은 조각은 15분이 안 돼 '관찰'로 남는다.", "",
          "## 판넬용 한 줄", "",
          "- 규칙은 **왜 그렇게 판정했는지 설명하기 쉽고**, 랜덤포레스트는 **여러 특징을 함께 보고 기준을 데이터로 정한다**.",
          "- 둘 다 '높음'은 확실할 때만 (잘못된 경보 0회 목표). 애매한 경우는 '관찰'로 남겨 쉬는 시간에 확인.",
          "", "![위치](위치_혼동행렬.png)", "", "![의심도](의심도_규칙_vs_RF.png)"]
    with open(os.path.join(OUT, "비교표.md"), "w") as fp:
        fp.write("\n".join(L) + "\n")
    print("\n".join(L[5:]))
    print(f"\n→ {os.path.abspath(OUT)}")


if __name__ == "__main__":
    main()

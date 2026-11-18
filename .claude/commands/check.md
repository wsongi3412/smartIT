---
description: run_all.py로 채점·AI 학습을 돌리고 결과를 쉬운 말로 설명
---
ExamSentry 채점을 돌리고 결과를 설명해 줘.

1. `data/` 에 실측 파일(`calib_day1.csv`, `calib_day2.csv`, `exams/day1`, `exams/day2`)이 있으면 그걸로, 없으면 가짜 데이터 데모로 `python run_all.py` 를 실행해.
2. 생성된 `results/.../report.md` 를 읽고 성공 기준(구역 정확도 ≥80%, 복도 오판 ≤10%, 숨긴 기기 90% 이상 '높음', 잘못된 경보 0회)별로 통과/미달을 쉬운 말로 설명해.
3. 혼동 행렬(`confusion.png`)에서 어디를 자주 헷갈리는지 짚어 줘.
4. 가짜 데이터 결과라면 "발표용 아님, 코드 확인용"이라고 분명히 말해.

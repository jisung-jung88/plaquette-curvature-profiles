# 연구 자산 색인 — plaquette-curvature-profiles

질문과 관련된 기록을 먼저 고르고, ID를 열어 조건·관측·해석·한계와 원래 근거를 확인한다.
이 목록과 ID별 페이지는 [records.json](records.json)에서 생성한다. [사용·기록 안내](README.md)를 따른다.

- 색인 갱신일: 2026-11-10
- 연구 기록: 11개. 실행 횟수·독립 표본 수와 구분한다.
- 확인한 근거 스냅샷: [bd4e4f24175d](https://github.com/jisung-jung88/plaquette-curvature-profiles/commit/bd4e4f24175d71a360f86bd88fda35c91ae30219)
- 현재 상태·남은 근거: [STATUS.md](STATUS.md)
- 수록 범위와 점검: [COVERAGE.md](COVERAGE.md), [검증 기록](VALIDATION.md)
- 관련 저장소: [jisung-jung88/kappa-profile](https://github.com/jisung-jung88/kappa-profile)
- 같은 ID의 명시된 mirror는 같은 자산의 다른 보관 위치다. 복사본을 독립 실행·독립 표본으로 세지 않는다. 새 기록의 mirror는 자동 생성하지 않는다.

저장소 루트에서 `python3 scripts/research_memory.py search <핵심어>`로 찾고, `show <ID>`로 한 기록을 읽을 수 있다. `--workstream`과 `--kind`로 범위를 좁힌다.
문자 일치 검색의 `NO_MATCH`는 관련 연구가 없다는 판정이 아니다. 다른 표현이나 아래 목록도 확인한다.

## 연구 기록

| ID | 질문·핵심 결과 | 종류 | 연구 묶음 |
|---|---|---|---|
| [KP-R001](entries/KP-R001.md) | 시뮬레이션 η3=0: n=2–7, 잡음·drift 아래 κ-profile sweep | simulation_campaign | [sim](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/sim) |
| [KP-R002](entries/KP-R002.md) | 시뮬레이션 η3=0.1: n=2–7, 잡음·drift 아래 κ-profile sweep | simulation_campaign | [sim](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/sim) |
| [KP-R003](entries/KP-R003.md) | 시뮬레이션 η3=0.2: n=2–7, 잡음·drift 아래 κ-profile sweep | simulation_campaign | [sim](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/sim) |
| [KP-R004](entries/KP-R004.md) | IBM Fez Day 1, η3=0·run=6: 누적 counts와 마지막 R8 metadata | qpu_campaign | [qpu](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/qpu) |
| [KP-R005](entries/KP-R005.md) | IBM Fez Day 1, η3=0.1·run=8: 누적 counts와 마지막 R8 metadata | qpu_campaign | [qpu](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/qpu) |
| [KP-R006](entries/KP-R006.md) | IBM Fez Day 1, η3=0.2·run=5: 누적 counts와 마지막 R8 metadata | qpu_campaign | [qpu](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/qpu) |
| [KP-R007](entries/KP-R007.md) | IBM Fez Day 2, η3=0·run=8: 누적 counts와 마지막 R8 metadata | qpu_campaign | [qpu](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/qpu) |
| [KP-R008](entries/KP-R008.md) | IBM Fez Day 2, η3=0.1·run=9: 누적 counts와 마지막 R8 metadata | qpu_campaign | [qpu](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/qpu) |
| [KP-R009](entries/KP-R009.md) | IBM Fez Day 2, η3=0.2·run=7: 누적 counts와 마지막 R8 metadata | qpu_campaign | [qpu](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/qpu) |
| [KP-R010](entries/KP-R010.md) | Schedule ablation: I1–I4 네 번의 512-shot interleaved 실행 | schedule_ablation_family | [qpu](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/qpu) |
| [KP-R011](entries/KP-R011.md) | Schedule ablation: 2048-shot blocked-by-setting 한 시도 | schedule_ablation_attempt | [qpu](https://github.com/jisung-jung88/plaquette-curvature-profiles/tree/bd4e4f24175d71a360f86bd88fda35c91ae30219/data/qpu) |

## 배경 자료와 복원 입구

- [저장소 사용법과 연구 배경](../../README.md)
- [보존된 QPU 결과와 실행 메타데이터](../../data/qpu)
- [보존된 simulator 결과와 실행 메타데이터](../../data/sim)
- [관련 저장소의 현재 색인](https://github.com/jisung-jung88/kappa-profile/blob/main/docs/research_memory/INDEX.md) — 현재 탐색 입구이며 고정 원문 근거와 구분한다.

## 읽을 때의 범위

- 11개는 의미 있는 연구 묶음 수이며 실행 횟수·독립 표본 수가 아니다. 내부의 59개 보존 메타데이터를 별도 inventory로 연결했다.
- 공통 KP-R ID의 두 저장소 기록은 같은 과거 관측의 보관 위치다. 중복 사본을 독립적인 근거로 세지 않는다.
- 원 질문·동기가 별도 사전 일지에 없으면 README·설정·분석 코드를 근거로 사후 복원했다고 표시한다.
- 실제 runtime Git commit·dirty 상태와 일부 누적 QPU 실행 계보는 미확인이다. 보관 snapshot을 실행 commit으로 추정하지 않는다.
- 이번 수량·산술 검산과 figure 재생성은 기존 관측의 확인이다. 새 QPU 획득이나 simulation campaign을 수행하지 않았다.

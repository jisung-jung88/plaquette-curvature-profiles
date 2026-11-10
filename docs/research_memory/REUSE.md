# 보존된 관측과 분석 코드 재사용

## 먼저 고를 것

재사용하려는 질문에 맞는 [기록](INDEX.md)을 고르고 모델·η₃·n·pair·날짜·shots·측정 순서를 확인한다.
원 관측은 `data/`, 설정·runner·모델은 `src/`, figure 분석은 `figures/`에 있다.
[STATUS.md](STATUS.md)의 실행 provenance 한계를 함께 읽는다.

| 목적 | 기존 분석 입구 | 연결 기록 |
|---|---|---|
| 시뮬레이션에서 n과 η₃별 통계 비교 | `figures/fig3/make_fig3.py` | KP-R001–003 |
| 시뮬레이션 n=7의 context별 profile | `figures/fig4/make_fig4.py` | KP-R001–003 |
| QPU Day 1의 n·η₃별 통계 비교 | `figures/fig5/make_fig5.py` | KP-R004–006 |
| QPU Day 1의 context별 profile | `figures/fig6/make_fig6.py` | KP-R004–006 |
| Blocked와 interleaved 측정 순서 비교 | `figures/fig7/make_fig7.py` | KP-R010–011 |
| Day 1과 Day 2의 비교 | `figures/fig8/make_fig8.py` | KP-R004–009 |

실제 명령은 [루트 README](../../README.md)의 Reproducing Figures 절에 있다.
현재 figure 스크립트는 보존된 파일을 읽어 후처리한다. QPU runner 실행과 구분한다.
원 README의 six commands는 2026-11-10에 기존 자료로 실행했으며 모두 exit code 0이었다.
새 hardware job이나 simulation acquisition을 수행하지 않았다. 자세한 환경과 검사 범위는 [VALIDATION.md](VALIDATION.md)를 따른다.

## 조건 선택을 생략하지 않기

Day 1은 η₃/run `0:6`, `0.1:8`, `0.2:5`이고,
Day 2는 `0:8`, `0.1:9`, `0.2:7`이다. 원 README의 명시적인 선택을 따른다.
`run=8`만으로는 η₃=0.1 Day 1과 η₃=0 Day 2를 구별할 수 없다.
원 JSON의 중첩 구조와 run 식별자를 함께 확인한다.

Fig.5 data 단계의 context pivot은 run을 key에 포함하지 않고 `first`를 취한다.
두 날짜를 담은 파일에서 `--eta-run`을 생략한 결과를 모든 날의 반복 비교로 사용하지 않는다.
Fig.7의 I12, I34, I_sum은 획득 구간을 합친 파생 자료다.
I_sum은 I1–I4의 총 2,048 shots이지 다섯 번째 interleaved 시행이 아니다.
Blocked의 job 4개도 네 measurement setting을 분리한 한 시행이다.

## 기존 자료를 다시 해석할 때

원 기록을 보존하고 새 분석 질문, 선택한 조건, 코드·입력 해시, 통계 처리, 관측과 한계를 남긴다.
새 해석 기록에서 사용한 과거 `KP-R…` 기록을 연결한다.
과거 코드가 이미 출력한 숫자인지, 이번에 다시 계산한 숫자인지, 원문 없이 추정한 해석인지 구분한다.
QPU 누적 counts의 일부 실행 계보가 없다는 한계는 후처리 성공으로 해소되지 않는다.

두 저장소의 동일 원 관측을 합쳐 표본 수를 늘리지 않는다.
별도 날짜·job의 실제 반복이 있더라도 독립성이나 재현성 주장은 해당 모델·설정·통계 범위에서 판단한다.
새 실행이 필요하면 [기록 절차](README.md)에 따라 실제 runtime provenance를 확보한다.

## 과거 실행 목록을 다시 검산하기

`python3 scripts/reconstruct_run_inventory.py`는 원 데이터와 메타데이터를 읽고
이번에 만든 과거 실행 목록을 JSON으로 출력한다. `--output`으로 별도 결과 경로를 지정하고,
`--metrics-output`으로 원 rows/counts의 산술 요약을 저장할 수 있다.
표준 라이브러리만 사용하고 simulator·QPU runner·네트워크를 호출하지 않는다.
39개 고정 원본의 해시가 다르면 일치하지 않음을 보고한다.
이 코드는 이번 과거 자료의 포맷을 복원하기 위한 것이며, 새 시행에 이 포맷을 강제하지 않는다.
이미 보존한 [실행 목록](historical_run_inventory.json)과
[산술 요약](verification/observed_metrics.json)을 먼저 읽으면 된다.

현재 재생성한 figure의 작은 요약 표와 입력·코드·환경 해시는
[verification/README.md](verification/README.md)에 있다. 원 과거 figure 출력과 구분한다.

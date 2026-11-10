# 현재 상태와 재사용 입구

확인일: 2026-11-10. 이번 정리 전 두 Git snapshot과 그 안의 실행 메타데이터·관측값을 대조했다.

**두 저장소는 동일한 과거 연구 자료를 보관한다. 11개 연구 묶음으로 조회할 수 있으며,
그 안의 59개 보존된 메타데이터 레코드는 개별 실행 정보로 연결했다.**
11개 기록, 59개 메타데이터 레코드, trial 수, job 수와 표본 수를 서로 구분한다.

## 보존된 연구 범위

| 범위 | 검색용 기록 | 확인된 자료 |
|---|---|---|
| 시뮬레이션 η₃=0, 0.1, 0.2 | [KP-R001](entries/KP-R001.md)–[KP-R003](entries/KP-R003.md) | n=2…7의 실행 정보 18개, n별 trial 360개, context 행 7,380개, pair-trial 요약 600개 |
| QPU Day 1의 세 η₃ 조건 | [KP-R004](entries/KP-R004.md)–[KP-R006](entries/KP-R006.md) | 보존된 counts와 n별 마지막 R8 메타데이터 18개 |
| QPU Day 2의 세 η₃ 조건 | [KP-R007](entries/KP-R007.md)–[KP-R009](entries/KP-R009.md) | 별도 날짜의 counts와 n별 마지막 R8 메타데이터 18개 |
| 측정 순서를 섞은 interleaved 조건 | [KP-R010](entries/KP-R010.md) | 별도 획득 I1–I4, 구간당 회로별 512 shots; I_sum은 네 구간을 합산한 파생 결과 |
| 설정별로 모아서 측정한 blocked 조건 | [KP-R011](entries/KP-R011.md) | 한 시행, 설정별 job 4개, 회로별 2,048 shots |

Day 1·Day 2는 원 README의 명시적인 η₃/run 선택에 따른 분석용 이름이다.
정확한 원 시각, run ID, job ID, JSON 내 위치는
[historical_run_inventory.json](historical_run_inventory.json)에 보존했다.
그 원본 위치와 숫자는 실제 data 파일로 다시 확인할 수 있다.

## 재사용할 때 특히 확인할 부분

**측정 수와 메타데이터 범위.** Main QPU counts의 각 histogram은 2,048 shots이며,
보존된 마지막 R8 메타데이터·header는 256 shots를 기록한다. 합산 결과와 마지막 구간의 설정을
별도로 다룬다. 앞선 모든 구간의 job·실행·합산 provenance가 보관됐다고 추정하지 않는다.
Interleaved의 네 512-shot 구간과 blocked의 네 설정별 job도 각각 다른 단위다.

**실행 성공과 누락된 이력.** 보존된 QPU 메타데이터 41개는 exit code 0을 기록한다.
시뮬레이션에는 종료 시각과 완전한 결과 범위가 있지만 같은 exit-code 필드는 없다.
보존된 자료에서 확인되지 않은 실패·중단·이전 run은 미확인이다. 모든 과거 시도가 성공했다고 해석하지 않는다.

**보관 commit과 실행 코드.** 실행 기록은 두 저장소에 자료가 업로드되기 이전의 것이다.
실제 runtime Git commit과 dirty 상태는 확인되지 않는다. 현재 코드와 설정은 고정된 보관 snapshot으로 연결한다.
QPU 메타데이터에 기록된 모델·backend snapshot 해시는 실제 파일과 대조했고,
이 파일 수준의 일치가 전체 runtime checkout·환경의 식별을 대신하지는 않는다.

**비교 조건과 해석.** η₃, n, 날짜, pair, 모델, seed와 측정 순서를 함께 확인한다.
시뮬레이션은 같은 seed base와 trial ID를 η₃/n 조건 사이에서 재사용한다.
360개 n별 trial 인스턴스나 600개 pair 요약을 독립 표본 수로 간주하지 않는다.
원 README의 figure 명령처럼 η₃/run 선택을 명시한다. Figure 5 등에서 선택을 생략한 기본 동작을
두 날짜의 독립적인 전체 비교라고 해석하지 않는다. 수치가 나온다는 사실과 과학적 주장 범위는 별도로 판단한다.

## 두 저장소의 관계

정리 전 각 저장소의 82개 파일 중 README와 tree 목록을 제외한 80개가 byte 단위로 같았다.
그중 실제 코드·설정·데이터·그림 코드·requirements 78개가 동일하다.
원 실행·job ID와 관측값도 같으므로 양쪽 자료는 같은 근거의 두 보관 위치다.
[관계와 Git 이력](RELATIONSHIP.md), [원본 파일 목록](source_inventory.json)을 따른다.

공통 과거 기록에는 양쪽 모두 같은 `KP-R…` ID를 사용한다. 한쪽을 공식 원본으로 지정하거나
다른 쪽을 폐기한다는 결정은 확인되지 않았으므로 어느 쪽도 임의로 권위 있는 저장소로 삼지 않았다.
새 kappa 기록은 `KAP-R…`, 새 plaquette 기록은 `PLQ-R…`로 만들어 기원과 후속 관계를 남긴다.

## 다음 연구를 시작하는 순서

관련 기록에서 원 데이터·설정·한계를 확인하고, 기존 결과의 재분석으로 답할 수 있는 질문인지 먼저 검토한다.
새 실행이 필요하면 실제 checkout·환경·변경 내용·job·결과의 provenance를 남긴다.
과거 전체 실행 순서를 복원하려는 경우에는 누락된 이전 구간의 원 로그와 합산 과정을 먼저 확보해야 한다.
확인되지 않은 자료는 새로 추측해서 채우지 않는다.

기존 관측값을 분석하는 경로는 [REUSE.md](REUSE.md), 앞으로의 기록 절차는 [README.md](README.md),
현재까지 수행한 검사는 [VALIDATION.md](VALIDATION.md)에 있다.

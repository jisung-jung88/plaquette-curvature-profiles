# 정리·검색·재사용 검증

검증일: 2026-11-10. 대상은 kappa-profile과 plaquette-curvature-profiles다.

**두 catalog의 구조·출처·상호 연결, 과거 실행 목록의 재검산, 기존 figure 명령 6개와
향후 기록 절차의 검증이 통과했다.** 원 관측의 전체 과학적 타당성이나 과거 실행 환경 전체를
재현했다고 해석하지 않는다. 이번에 새 QPU 획득이나 simulation campaign을 수행하지 않았다.

## 원문과 기록 구조

| 검사 | 결과 |
|---|---|
| 두 원본 snapshot의 164개 경로 인스턴스 | 원 Git blob·byte count·SHA-256 대조 |
| 전체 원 Git 이력 | kappa 9개·plaquette 3개 commit, 모든 parent와 6개 tag 확인 |
| 실제 Git 객체 복원 | 현재 81개·과거 전용 19개 고유 blob을 포함하여 exact SHA 대조; 양쪽 git fsck 통과 |
| 각 catalog의 11개 공통 역사 기록 | 구조 검사 통과; 같은 ID는 같은 자산의 보관 위치 |
| 각 catalog의 177개 근거 참조 | 기존 고유 path/commit/blob 56개와 새 같은-commit source 6개를 실제 내용으로 대조 |
| 각 catalog의 36개 방향 관계 | 역방향 관계 모두 존재 |
| 양쪽 11개 같은-ID 연결 | 상대 기록 존재, 역방향 mirror, 의미·공통 원문 일치 |
| 각 catalog의 생성 페이지 12개 | JSON과 일치 |
| 새 안내와 생성 페이지 | 로컬 링크 및 양쪽 Git source 경로 확인 |
| 기존 원 파일 보존 | README 안내·설치 URL·shot 설명 외 원 파일 변경·삭제 없음 |

현재 main으로 이동하는 mirror는 탐색 링크이고, 고정된 원문 근거는 commit/path/blob 링크다.
서로 다른 저장소의 같은 파일을 독립 관측으로 세지 않도록 표시했다.
등록한 source inventory는 양쪽 원본 82개 파일 전체를 포함한다.

## 실행 메타데이터와 관측값 대조

- 11개 연구 묶음의 원 run ID가 보존된 59개 메타데이터 레코드를 빠짐없이 한 번씩 분할한다.
- 시뮬레이션 18개 execution, 7,380 context 행과 600 pair-trial summary의 조건 범위가 맞는다.
  n별 trial 인스턴스는 360개다. 같은 seed base와 trial ID의 조건 간 재사용을 명시했다.
- 600개 시뮬레이션 통계 요약을 원 rows에서 재집계했다. 최대 V 오차는 약 4.89×10⁻⁸이며,
  작은 V를 세 유효숫자로 저장한 반올림 범위와 일치한다. 다른 확인한 요약 오차는 10⁻⁹ 미만이다.
- QPU 4,136개 histogram의 count 합과 entry shots를 확인했다. 전체 측정 합은 6,897,664이며,
  pair/context/setting의 예상 조합이 빠짐없이 존재한다.
- 보존된 QPU 메타데이터 41개가 가리키는 모델·backend snapshot hash가 실제 원 bytes와 일치한다.
- Main QPU의 유효 2,048-shot histogram과 마지막 R8의 256-shot 설정을 분리했다.
  없는 이전 구간의 job·상태·합산 이력을 만들어 넣지 않았다.
- Interleaved 획득 4개, blocked 시행 1개, blocked의 설정별 job 4개와 pooled I_sum을 구분했다.
- 원 timestamp와 한국시간을 대조하고, run 이름의 숫자를 실행 시각의 대용으로 사용하지 않았다.

출판한 `scripts/reconstruct_run_inventory.py`는 표준 라이브러리만 사용한다.
39개 역사적 원본 hash를 확인하고 같은 원 자료에서 목록과 산술 요약을 재생성한다.
양쪽 checkout에서 출력이 byte 단위로 같았고, 실제 설치 경로에서 생성한 결과도 보존 JSON과 정확히 같았다.
원 metadata·관측과 이 정리의 사후 산술 결과를 [실행 목록](historical_run_inventory.json),
[산술 요약](verification/observed_metrics.json)에 구분했다.

## 기존 관측의 분석 경로 재사용

원 README에 있던 Fig.3–8 명령 6개를 그대로 사용하고 출력만 별도 위치에 썼다.
모두 exit code 0이었다. Bootstrap이 있는 분석은 원 기본값 5,000회와 원 seed를 유지했고,
QPU는 명시적인 Day 1·Day 2의 η₃/run 선택을 적용했다.

| 환경 | 실제 확인한 값 |
|---|---|
| Python | 3.12.14 |
| NumPy | 2.3.5 |
| Pandas | 2.2.3 |
| Matplotlib | 3.10.8 |
| PyYAML | 6.0.3 |
| Plot backend | Agg |

원 source/data/requirements 78개 해시가 실행 전후 같았다.
실행 당시 원 source checkout은 전후 clean이었고, 원 파일을 고치거나 패키지를 설치하지 않았다.
생성 manifest의 입력 hash 주장 17개도 원 bytes와 대조했다.
stderr에는 font metadata timestamp 경고가 반복됐지만 명령 실패는 없었다.

[작은 재생성 결과 묶음](verification/README.md)은 요약 CSV 11개와 환경·명령·코드·입출력 hash를 담는다.
이 표들은 **2026-11-10의 재생성 결과**이며 과거 원 publication figure bytes가 아니다.
기존 결과를 읽고 다시 계산할 수 있음을 확인한 범위이고, 누락된 runtime provenance를 복구한 것은 아니다.
Raw V_circ와 bootstrap-median V_circ_point, 합산된 조건과 별도 획득을 구분한다.

## 처음 보는 AI의 검색·출처 검수

추출 작업의 예상 답을 제공받지 않은 별도 검수자가 실제 `list`, `search`, `show`, `locate`를 사용하고
필요한 원문까지 따라갔다. 두 저장소의 관계, 기록/run/trial/job의 단위, simulator 조건,
QPU 측정 수와 메타데이터, Day 선택, schedule·합산 비교, 미기록 실패,
runtime provenance, raw·bootstrap 수치, 향후 기록·mirror 운영을 검토했다.

독립 검수에서는 양쪽 원 snapshot의 82개 파일씩, 59개 metadata selector·시각·설정,
41개 QPU 모델·snapshot 참조와 count 묶음, 600개 simulator 요약을 대조했다.
QPU histogram 4,136개와 simulator 행 7,380개의 조합 범위, verification input hash 35개,
보존된 표 11개의 hash·schema도 일치했다. 중대한 의미 오류나 누락된 상호 연결은 발견되지 않았다.

영어 `failure`가 처음에는 매치되지 않는 조회 문제를 발견해 `failure history unknown`과
`실패 이력 미확인` 별칭을 추가했다. 다시 조회해 두 저장소 모두에서 관련 기록을 찾았다.
이 별칭은 관측된 실패를 새로 주장하지 않고 원 실패 이력의 미확인 범위를 가리킨다.
검색은 문자 일치이며, 검색 실패를 연구 부재로 해석하지 않는 규칙을 유지했다.

기존 source는 `locate`로 정확히 찾았고, 아직 첫 commit에 들어가지 않은 새 파생 source는
`NOT_IN_LOCAL_HISTORY`로 구분했다. 같은 commit에 원문과 catalog를 넣는 동작은 아래 검사에서 확인했다.

## 향후 기록 절차 검사

실제 임시 Git 저장소를 이용한 **28개 항목이 통과**했다. 합성 기록은 실제 catalog에 추가하지 않았다.

- 원문·catalog를 한 commit에 넣고 null self-commit을 정확한 path/blob로 찾기.
- 현재 파일이 바뀐 뒤에도 과거 원문 찾기; 없는 이력·commit·경로·tree·다른 blob 구분.
- 미래 KAP/PLQ ID, 실제 같은-ID mirror만 허용, 새 로컬 기록의 상대편을 자동 생성하지 않기.
- 외부 source의 repository/URL/manifest 연결 및 로컬의 같은 blob을 외부 provenance로 오인하지 않기.
- 실행 없는 조사, 부분·실패한 dirty 실행, 후속 재해석과 모르는 runtime identity 표현.
- 페이지 drift 검출·재생성, 예상하지 못한 이전 페이지를 조용히 삭제하지 않기.
- 읽기 전용 조회와 오프라인 실행.

## 보존과 게시 검증

게시 대상은 README, 새 AGENTS, 조회·복원 도구와 research_memory 문서·작은 결과 묶음으로 한정한다.
토큰·private key·서명 URL·webhook 노출 패턴은 발견되지 않았다.
실행 캐시·환경·큰 그림 파일·API response cache는 게시 대상에서 제외한다.
각 repo는 원 main을 parent로 하는 관리 commit을 사용하며 원 tag와 역사적 source를 보존한다.
게시할 때는 준비한 전체 tree의 파일 hash·mode를 대조하고, expected-head 조건으로 main을 갱신한 뒤
원격 main·주요 문서·양쪽 연결·기존 tag를 다시 읽어 확인한다.

[현재 상태](STATUS.md) · [정리 범위](COVERAGE.md) · [향후 기록 절차](README.md)

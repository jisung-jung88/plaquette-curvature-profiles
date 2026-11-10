# Kappa / Plaquette 연구 자산의 조회와 기록

목표는 **의미 있는 시행마다 독립적으로 찾아서 이해하고 재사용할 수 있는 기록을 남기고,
그 기록을 유지하는 수고를 Codex의 작업 절차 안에서 작게 만드는 것**이다.
실행, 반복, 실패, 중단, 조사, 설계와 후속 해석을 근거가 허용하는 범위에서 기록한다.

## 기존 자산 찾기

1. [STATUS.md](STATUS.md)에서 확인한 현재 상태와 아직 모르는 부분을 읽는다.
2. [INDEX.md](INDEX.md)나 `search`로 관련 질문·시행을 고른다.
3. 조건·관측·해석·한계와 이전·후속 관계를 읽는다.
4. 숫자나 결론을 사용할 때 원 run metadata, counts/rows, 설정과 코드의 고정 출처를 확인한다.
5. 같은 ID의 다른 저장소 기록은 보관 위치를 넓혀 주는 mirror다. 독립 재현이나 추가 표본으로 세지 않는다.

```bash
python3 scripts/research_memory.py list
python3 scripts/research_memory.py search QPU
python3 scripts/research_memory.py search 'block'
python3 scripts/research_memory.py show KP-R001
python3 scripts/research_memory.py locate KP-R001
```

검색은 대소문자를 구분하지 않는 문자 일치다. 여러 검색어는 OR로 조회하고,
제목·검색어, 요약·질문, 나머지 상세 내용 순서로 가중치를 준다. 기본 반환 개수는 5개다.
`--limit`, `--kind`, `--workstream`으로 범위를 조절한다. `NO_MATCH`는 연구 부재 판정이 아니다.
다른 표현과 전체 목록도 확인한다. 도구는 표준 라이브러리만 사용하며 네트워크나 실험을 실행하지 않는다.

## 파일 역할과 기록 단위

| 파일 | 역할 |
|---|---|
| [records.json](records.json) | 연구 기록의 편집 원본 |
| [INDEX.md](INDEX.md), `entries/*.md` | JSON에서 생성한 목록·상세 페이지 |
| [STATUS.md](STATUS.md) | 확인 시점의 상태·남은 근거·다음 연구 전 확인 사항 |
| [COVERAGE.md](COVERAGE.md), [VALIDATION.md](VALIDATION.md) | 정리 범위·한계와 실제 검사 결과 |
| [historical_run_inventory.json](historical_run_inventory.json), [source_inventory.json](source_inventory.json) | 이번 확인일의 과거 실행 복원과 출처 대조 snapshot |
| [scripts/research_memory.py](../../scripts/research_memory.py) | 조회·구조 검사·페이지 생성·로컬 Git 출처 조회 |
| 기존 `data/`, `src/`, `figures/`와 원 보고서 | 보존된 관측, 실행 메타데이터, 코드·설정과 분석 절차 |

하나의 질문과 관측·판단·한계를 함께 재사용할 수 있는 단위를 연구 기록으로 삼는다.
같은 질문의 seed·trial·하위 조건은 원 실행 식별자를 보존하며 묶을 수 있다.
후속 재분석이나 해석 정정은 새 기록으로 연결한다. 관리·오탈자·포맷 변경에 연구 항목을 억지로 만들지 않는다.
기존 원 보고서가 있으면 연결하고 같은 내용을 여러 문서에 손으로 복제하지 않는다.
생성 페이지를 직접 고치지 않고 `records.json`을 고친 뒤 다시 생성한다.
과거 복원 inventory는 확인일이 있는 snapshot이다. 새 시행마다 이 큰 파일들을 손으로
다시 작성할 필요는 없다. 기존 원 run metadata·보고서를 보존하고 검색용 기록과 필요한 관계를 추가한다.
과거 inventory 자체를 정정할 근거가 생겼을 때만 정정 이유와 변경 범위를 남긴다.

### 두 저장소에서 같은 연구를 식별하는 방법

`KP-Rxxx`는 이번에 복원한 공통 역사 기록의 ID다. 두 저장소의 같은 ID는 같은 연구 자산을 가리킨다.
미래에 kappa-profile에서 시작하는 새 기록은 `KAP-Rxxx`, plaquette-curvature-profiles에서는 `PLQ-Rxxx`를 쓴다.
해당 namespace에서 사용하지 않은 번호를 고르고, 이미 사용한 ID를 다른 질문에 재사용하지 않는다.
나중에 기록을 다른 저장소로 복사해도 원 ID를 보존한다.

- **동일 실행의 복사본:** 같은 ID와 원 실행·결과 식별자를 보존하고 보관 위치를 연결한다.
- **같은 조건의 별도 실행:** 새 실행·연구 기록 ID와 원 시행에 대한 반복 관계를 남긴다.
- **조건을 바꾼 후속 시행:** 새 ID와 무엇을 바꿨는지, 선행 시행과의 관계를 남긴다.
- **과거 결과의 재분석:** 새 해석 기록을 만들고 사용한 원 실행을 연결한다. 새 QPU 실행으로 세지 않는다.

복사본 여부는 이름만으로 결정하지 않는다. 실제 파일 내용과 실행 ID·작업 ID·시간·조건을 대조한다.
설정이나 결과 바이트가 같다는 사실만으로 같은 실행을 확정하지 않는다. 결정적인 계산을
별도로 반복하면 같은 바이트가 나올 수 있다. 이력과 원 run/job 식별자를 함께 확인한다.
같은 데이터가 두 저장소에 있다고 독립 근거가 두 개가 되지는 않는다.
Git에 처음 올라온 commit은 보관 시점일 수 있다. 실제 실행 시점이나 runtime checkout으로 추정하지 않는다.

각 기록의 `mirrors`에는 실제로 존재하는 같은 ID의 보관 위치만 적는다.
항목은 `repository`, `id`, `path`를 사용하며 경로는 `docs/research_memory/entries/<ID>.md`다.
새 로컬 기록은 `mirrors: []`로 시작한다. `peer_repository`가 있다고 모든 새 기록의 상대편 페이지를 만들지 않는다.
mirror 링크는 상대 저장소의 현재 main 탐색용이다. 원문을 증명하는 고정 commit·blob 링크와 구분한다.
두 catalog의 변경이 자동 동기화되는 서비스는 없다. 관계를 바꾼 작업에서는 상대편 안내도 맞추거나 남은 갱신을 명시한다.
공통 과거 기록에 대해 한쪽에서 새 해석을 얻으면 `KAP-Rxxx` 또는 `PLQ-Rxxx` 후속 기록으로
그 근거와 원 시행을 연결한다. 다른 쪽에 같은 해석이 이미 적용됐다고 표시하지 않는다.

## 상태와 출처를 구분하기

| 항목 | 기록할 내용 |
|---|---|
| `execution_status` | 조사, 설계, 실제 실행, 부분 실행, 오류·중단, 후처리, 결과 미확인 등 |
| `evidence_level` | 계획, 코드, 실행 메타데이터, 실제 counts/rows, 통계 요약, 독립 검증 등 |
| `scientific_status` | 관측에 따른 긍정·부정·혼합·미판정과 성립 범위 |
| `approval_status` | 원 근거에서 확인되는 승인 범위 또는 미기록 상태 |

`original_status_terms`에는 원문 표현을, `status_basis`에는 현재 해석의 근거를 남긴다.
실행 가능 코드, figure 생성 코드, 완료된 job, 모든 목표 조건 완료, 과학적 결론은 각각 다른 주장이다.
실패·중단 시 완료한 조건과 반환된 counts를 보존하고, 없는 결과를 성공이나 0으로 채우지 않는다.
후속 정정에서는 원 관측, 분석 오류, 해석 변경을 구분한다.
뒤늦게 복원한 질문·이유는 복원이라고 표시하며 원래의 사전 가설처럼 표현하지 않는다.

실제 runtime commit을 모르면 `provenance.code_commit=null`로 남기고 `code_commit_note`에 이유를 쓴다.
알려진 보관 snapshot은 `result_commit`과 evidence의 고정 commit으로 연결한다.
실행 코드가 dirty였다면 실행한 diff·변경 파일의 해시와 설정을 원 run metadata/manifest에 보존한다.
기존 commit이나 현재 코드와의 일치 여부를 확인하지 않은 상태에서 실제 runtime identity로 복사하지 않는다.
실행 없는 조사에는 가짜 job/run ID가 필요 없다.

## 향후 Codex 작업의 완료 절차

새로운 시행·조사·실패·중단·재분석·정정이 생기는 승인된 작업에서는 다음을 함께 마친다.

1. **원 근거를 남긴다.** 질문, 이유, 실제 조건, 결과·오류, 해석·한계와 실행·설정 출처를 기존 위치에 보존한다.
2. **검색용 기록을 갱신한다.** 안정적인 ID와 실제 원문을 연결한다. 새 반복·후속 시행과 기존 복사본을 구분한다.
3. **관계를 연결한다.** 중요한 후속 판단은 이전 기록에서도 찾을 수 있게 한다. 이전 실패와 부정적 결과를 보존한다.
4. **목록과 검증을 맞춘다.** 실제 상태가 달라지면 STATUS를 갱신하고 구조·생성 검사, 원문 내용·해시, 실제 변경에 필요한 기존 검증을 수행한다.
5. **현재 허용된 Git 경로로 반영한다.** 커밋 본문과 최종 보고에 질문·이유·조건·관측·한계·기록 ID·근거·검사 결과·남은 일을 남긴다.

```bash
python3 scripts/research_memory.py validate
python3 scripts/research_memory.py render
python3 scripts/research_memory.py render --check
```

`validate`는 선언된 구조·식별자·출처 문법을 검사한다. 실제 원문 바이트, 원격 객체의 존재,
mirror 페이지의 존재, 과학적 타당성이나 실행 허가를 증명하지 않는다. 상호 참조는 실제 양쪽 내용을 대조한다.
`render --check`는 생성 페이지와 JSON의 일치를 읽기 전용으로 확인한다.
예상하지 못한 상세 페이지는 자동 삭제하지 않으므로 기록 ID와 보존 이력을 명시적으로 정리한다.
커밋 수와 문서 수는 고정하지 않는다. 이번 관리 작업으로 새 QPU 실행이나 유료 자원 사용 권한이 생기지 않는다.
두 저장소는 공개 저장소다. 새 원문·manifest·보고서에도 자격 증명과 비공개 입력을 포함하지 않는다.

### 원문과 색인을 같은 커밋에 넣기

이미 있는 출처는 full commit SHA와 정확한 Git blob SHA로 고정한다.
새 보고서·manifest와 색인을 한 커밋에 올릴 때에는 최종 바이트의 blob SHA를 계산하고,
`evidence.commit=null`, `evidence.url=null`, 정확한 `evidence.blob_sha`와 설명 `commit_note`를 남긴다.
`provenance.result_commit=null`의 이유도 적고 그 정확한 원문을 실제로 함께 포함한다.
원문 내용이 바뀌면 blob SHA도 다시 계산한다. 미래의 자기 commit SHA를 추측하지 않는다.

`locate <ID>`는 로컬 이력에서 경로와 blob이 모두 같은 출처를 찾는다.
얕은 clone, 없는 commit·경로, blob 불일치와 tree object를 구분한다. fetch나 파일 수정을 하지 않는다.
찾은 SHA는 이후 통상적인 갱신에서 채울 수 있고, 해시 채우기 전용 추가 커밋은 필수가 아니다.

출처가 다른 저장소에 있으면 evidence에 `repository`를 적고 그 저장소의 정확한 commit·경로·blob으로 연결한다.
이 경우 `locate`는 `EXTERNAL_REPOSITORY_NOT_SEARCHED`를 반환한다. 로컬에 같은 바이트가 있어도
외부 저장소의 출처를 확인한 것으로 바꾸지 않는다. 외부 저장소의 고정 URL·checkout에서 별도로 확인한다.
provenance의 commit들이 모두 다른 저장소에 속하면 `provenance.repository`를 지정한다.

## 큰 자료와 외부 자료

큰 결과물은 원래 저장 위치를 유지하고 실제 URI, 객체 버전, 크기·해시와 확인 범위를 manifest로 연결한다.
현재 없는 파일·S3 key를 해시나 이름에서 만들어 내지 않는다. 미확인 상태는 그대로 남긴다.
artifact의 `manifest_path`는 같은 기록의 evidence에 연결한다. manifest가 외부 저장소 출처라면
`manifest_repository`도 지정해 같은 이름의 로컬 파일과 구분한다.

| `verification` | 확인 범위 |
|---|---|
| `recorded_in_repository_not_rechecked` | 원래 기록된 위치를 보존; 원격 객체 재확인 안 함 |
| `object_listed_not_content_verified` | 목록·메타데이터 확인; 전체 바이트 미검증 |
| `selected_archive_members_reverified` | 정확한 객체 버전의 일부 ZIP member 내용 검증; 전체 ZIP 미검증 |
| `exact_version_reverified` | 정확한 버전 전체 내용을 확보하고 기록된 내용 해시 대조 |

목록, ETag, 일부 파일의 hash와 전체 archive SHA-256을 혼동하지 않는다.
내용 hash 일치는 과학적 주장이나 새 실행 허가를 대신하지 않는다.

## 커밋 요약과 작업 재개

커밋 본문에는 `Question`, `Why`, `Change`, `Conditions`, `Observed`, `Interpretation`,
`Evidence`, `Follow-up`을 짧게 남긴다. 긴 비교·분석은 원 보고서로 연결한다.
오래된 세션이나 branch를 이어갈 때 현재 main의 AGENTS·STATUS와 실제 사용하려는 코드·자료를 확인한다.
진행 중인 변경과 역사적 원문을 보존하며 규칙·색인·도구를 작업 환경에 반영한다.
완료 보고는 기록 ID, 실제 게시 상태, 검사 결과, 누락된 근거와 미완료 작업을 구분한다.

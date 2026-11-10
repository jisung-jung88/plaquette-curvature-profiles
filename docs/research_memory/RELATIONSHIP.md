# Kappa와 Plaquette의 관계와 과거 이력

확인일: 2026-11-10. 근거는 [source_inventory.json](source_inventory.json)과
[history_relationship.json](history_relationship.json)이다.

## 동일한 자산의 두 보관 위치

| 항목 | kappa-profile | plaquette-curvature-profiles |
|---|---|---|
| 정리 전 main | [a49a198](https://github.com/jisung-jung88/kappa-profile/commit/a49a198e6327f42323e0f43c17ef58d8c535c15c) | [bd4e4f2](https://github.com/jisung-jung88/plaquette-curvature-profiles/commit/bd4e4f24175d71a360f86bd88fda35c91ae30219) |
| 기존 commit 수 | 9 | 3 |
| 기존 tag 수 | 4 | 2 |
| 원 파일 수 | 82 | 82 |
| 원본 데이터·구현·그림 코드·requirements | 동일한 78개 파일 | 동일한 78개 파일 |

그 밖의 LICENSE와 gitignore도 같다. README와 tree_structure.txt만 다르다.
공통 commit 객체는 0개지만 같은 bytes와 같은 실행·job 식별자를 보관한다.
따라서 Git 이력이 다르다는 이유로 이 자료를 독립적인 반복 실험으로 세지 않는다.
동일한 조건이나 byte 일치만으로 모든 미래 실행까지 중복으로 판정하는 규칙도 아니다.
새 실행의 식별자와 실제 획득 과정을 함께 확인한다.

Kappa의 업로드가 더 이르고 plaquette가 나중 이름을 사용한다는 사실만으로 최초 자료의 기원,
직접 복사 방향, 공식 후계 저장소 또는 폐기 결정을 확정할 수는 없다.
이번에는 두 저장소와 모든 기존 tag를 보존하고 상호 탐색을 연결했다.

## Commit이 실제로 남긴 변화

Kappa는 2026-02-04의 초기 구성 후 같은 날
[ed862c5](https://github.com/jisung-jung88/kappa-profile/commit/ed862c55b4e1b19773af4b69c6aa70f872bfb276)에서
코드·관측값·그림 자료를 올렸다. v1.0.0 release 설명은 Quantum 제출 자료라고 적는다.
이후 일부 그림·README·tree 목록을 제거한 뒤 v2.0.0에서 새 출판 구성으로 다시 올렸다.
v2.0.0 release 설명은 Physical Review A 제출용 그림 갱신을 기록한다.
이는 release가 말하는 제출 맥락이며 게재 승인이나 과학적 유효성 판정이 아니다.

`src/`, `data/`, `requirements.txt`는 첫 자료 업로드 이후 현재까지 같은 내용이다.
그림 data 단계도 Fig.3–6은 동일하고, 예전 Fig.8의 순서 비교가 현재 Fig.7로,
예전 Fig.9의 날짜 비교가 현재 Fig.8로 이동했다. 뒤의 두 data 스크립트는 주석·식별자 변경이며,
plot·wrapper에는 출판용 배치·스타일 변화가 있다. 파일 이동·재업로드를 새 데이터 획득으로 세지 않는다.

Plaquette는 2026-02-13의 초기 구성 후
[00635d5](https://github.com/jisung-jung88/plaquette-curvature-profiles/commit/00635d5d5ae3cf459cc3bde32b2524aab4352640)에서
기존 자료를 올렸고, 2026-03-06의 bd4e4f2는 README만 추가했다.
실행 메타데이터의 관측 시점은 두 저장소의 최초 commit보다 앞선다.
업로드 commit은 보존된 자료의 위치와 버전을 식별하지만 실제 runtime commit을 증명하지 않는다.

## 보존한 release/tag

| 저장소 | Tag | 원 commit |
|---|---|---|
| kappa | v1.0.0 | ed862c55b4e1b19773af4b69c6aa70f872bfb276 |
| kappa | v2.0.0 | 4f58990ed63545c3388613458b3c27ef393efa2e |
| kappa | v2.0.1 | a7dfd3f206f3a52d1d0845bb6ff9dd83e86ec403 |
| kappa | v2.0.2 | a49a198e6327f42323e0f43c17ef58d8c535c15c |
| plaquette | v1.0.0 | 00635d5d5ae3cf459cc3bde32b2524aab4352640 |
| plaquette | v1.0.1 | bd4e4f24175d71a360f86bd88fda35c91ae30219 |

모두 commit을 가리키는 lightweight tag다. Release에 별도로 업로드된 artifact는 없었다.
이전 그림 구성은 해당 tag와 commit에서 조회할 수 있다.

## 같은 자산과 후속 작업을 연결하는 규칙

- 양쪽의 같은 `KP-R…` 기록은 하나의 과거 연구 자산이다. `mirrors`는 보관 위치 안내다.
- 원문 근거는 각 저장소의 정확한 commit·path·blob으로 고정한다. 현재 main의 mirror 링크와 구분한다.
- 새 실행과 후속 해석에는 기원 저장소의 새 `KAP-R…` 또는 `PLQ-R…` ID를 부여한다.
- 같은 결과를 재분석할 때 새 실행으로 세지 않고 사용한 원 관측을 연결한다.
- 상대편에 실제 같은 ID가 있을 때 mirror를 추가한다. 자동 동기화나 자동 복제는 구성하지 않았다.

[전체 기록](INDEX.md) · [향후 기록 절차](README.md)

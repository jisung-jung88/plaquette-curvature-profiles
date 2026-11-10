# 정리 범위와 근거의 한계

확인일: 2026-11-10. 이 문서는 이번에 읽고 대조한 범위를 명시한다.

## Git 범위

두 저장소의 원 main에서 도달 가능한 전체 이력을 확인했다. Kappa 9개, plaquette 3개 commit이며
각각 선형 이력이고 누락된 parent는 없다. 원 main branch 외 다른 branch나 열린·닫힌 PR은 조회되지 않았다.
여섯 tag와 release 설명을 확인했고 별도 uploaded release asset은 없었다.
이 조사는 접근한 refs에 대한 것이며 삭제된 원격 branch, 로컬에만 남은 작업과 다른 저장소를 전부 복원한 것은 아니다.

현재 source snapshot은 각 82개 파일, 두 저장소를 합쳐 고유 blob 81개다.
현재에는 없는 역사적 blob 19개도 읽어 총 100개 고유 blob과 실제 Git 객체를 복원했다.
두 checkout의 `git fsck --full --strict`가 통과했다.
현재 source 164개 경로 인스턴스는 원 blob SHA와 byte count를 대조했고,
[source_inventory.json](source_inventory.json)에 SHA-256도 함께 기록했다.

README와 tree_structure.txt 이외의 80개 경로가 같다. 실제 재현 자료 78개와 LICENSE/gitignore 2개다.
같은 원 관측에 대한 보관 위치가 둘이라는 점을 [RELATIONSHIP.md](RELATIONSHIP.md)에 명시했다.

## 연구 기록과 실행 정보

[INDEX.md](INDEX.md)의 11개 기록은 질문·조건별 연구 묶음이다.
[historical_run_inventory.json](historical_run_inventory.json)은 이를 구성하는
18개 simulation, 36개 main QPU 마지막 R8, 4개 interleaved, 1개 blocked 메타데이터를 보존한다.
합계 59개는 메타데이터 레코드 수이며 59회의 완전한 독립 연구를 뜻하지 않는다.

시뮬레이션의 7,380 context 행과 600 pair-trial summary를 실제 읽고 조건별 범위를 대조했다.
n별 trial은 360개이고, 여러 pair의 요약은 같은 trial에서 파생될 수 있다.
같은 seed base와 trial ID가 η₃/n 조건 사이에서 반복되므로 조건 간 통계적 독립성을 가정하지 않는다.
QPU 전체 자료의 4,136 count entry, histogram 총량 6,897,664 shots와
보존된 고유 job ID 44개를 메타데이터와 구분해 기록했다.
Job 수와 shot 수는 독립 반복 수·통계적 독립 표본 수를 뜻하지 않는다.

41개 QPU 메타데이터가 참조하는 모델 YAML 및 backend snapshot의 원 byte hash를 대조했다.
시뮬레이션의 600개 통계 요약은 원 rows에서 다시 계산해 저장 정밀도 범위의 일치를 확인했다.
각종 수량, 확인 범위, 개별 실행 ID·위치·한계는 inventory의 `count_checks`,
`model_snapshot_hash_checks`, `simulation_summary_recalculation`, `executions`를 따른다.

## 명시적으로 남긴 미확인 부분

- 원 run 당시의 Git checkout, dirty diff와 전체 환경은 확인되지 않는다.
- Main QPU의 누적 histogram은 2,048 shots지만 보존된 메타데이터는 마지막 R8의 256-shot 설정이다.
  이전 모든 구간의 원 counts·job receipt·합산 스크립트·계보가 확보됐다는 뜻이 아니다.
- 원 wrapper의 run 번호는 문자·숫자 표현을 그대로 보존한다. 빠진 번호의 시도를 이름만으로 만들어 내지 않는다.
- 보존된 QPU exit code 0과 일치한 데이터는 확인된 범위다. 다른 실패·중단·누락 시행의 존재 여부를 결론내리지 않는다.
- 원문에 사전 질문·동기가 독립 연구 일지로 남아 있지 않은 부분은 README·설정·분석 코드로 사후 복원했다고 표시한다.
- 기존 그림 코드의 존재와 이번 재생성 성공은 과거 publication figure bytes나 논문 결론 전체의 재현을 뜻하지 않는다.
- 현재 사용해야 할 공식 단일 저장소가 어느 쪽인지는 정해져 있지 않다.

이번에 확인한 보존 자료는 Git 안에 있다. 여기에서 구체적으로 연결되지 않은 외부 저장소,
개인 로컬 폴더·이전 job 서비스의 전체 이력을 임의로 확인했다고 주장하지 않는다.

## 향후 유지 범위

`historical_run_inventory.json`, `source_inventory.json`, `history_relationship.json`은 확인일의 복원 snapshot이다.
미래 시행 때마다 이 큰 파일들을 손으로 재작성할 필요는 없다.
새 원 근거와 짧은 검색용 기록을 연결하고 생성 페이지·관계를 갱신하는 절차를 [README.md](README.md)에 둔다.
검사 결과는 [VALIDATION.md](VALIDATION.md), 기존 관측 재사용 방법은 [REUSE.md](REUSE.md)에 있다.

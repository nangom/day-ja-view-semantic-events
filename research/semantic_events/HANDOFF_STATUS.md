# Semantic Events 담당 범위 및 진행 상태

기준 문서는 팀 저장소 `DAY-JA-VIEW`의 2026-08-11
`codex/overnight-bootstrap` 브랜치다. 이 저장소는 Q2 Core 중 다음 두 영역만 담당한다.

1. Geopolitical Event: UCDP GED 기반 중동 무력충돌 Episode
2. Policy/Regulation Event: Federal Register 기반 미국 정책·규제 Episode

Numeric 시계열, Event Study, 프론트, Q5 유사 장세는 담당 범위가 아니다.

## 팀 T04 완료 조건

- UCDP GED를 버전 고정으로 수집한다.
- 중동 무력충돌을 명시적 규칙으로 Episode화한다.
- Federal Register에서 대중국 반도체 수출통제 정책 Episode를 만든다.
- 각 Episode가 EventKind IRI, occurrence, public availability, region/target,
  Evidence ID·URL·hash를 가진다.
- LLM을 사용하지 않는다.
- 필수 필드·시간·중복·관계 검증 통과 시 자동 accepted 한다.
- 대표 조회 `ArmedConflict.Escalation AND MiddleEast`와
  `ExportControl AND targetsAgent=China`가 각각 1건 이상이어야 한다.

## 완료한 구현

### UCDP / 지정학

- GED 26.1 공식 ZIP 전체 다운로드와 CSV 스트리밍 처리
- 토큰 기반 UCDP REST API, 버전·날짜·지역·페이지 처리
- 원본 row와 SHA-256 불변 저장
- 중동 지역 + best-estimate 사망자 25명 이상 v1 규칙
- `djv:Escalation`, `occurredIn=MiddleEast` 생성
- `side_a`, `side_b`를 `hasParticipant` 관계로 저장
- UCDP conflict를 `partOfEvent` 관계로 저장
- 발생일과 최초 수집 가능 시각 분리
- UCDP 공식 레코드 URL과 원본 hash를 Evidence로 저장
- 같은 입력 재실행 시 중복 삽입 방지

실데이터 검증 결과: GED 26.1 417,968행, accepted Episode 3,780건,
기간 1989-01-01~2025-12-03, pending 0건.

### Federal Register / 정책·규제

- 공식 API 날짜·검색어·페이지 수집
- raw JSON, document revision, Evidence span과 hash 저장
- 중국 + 반도체 + 수출통제 강화 조건을 모두 만족할 때만
  `djv:ExportControlTightening` 생성
- `targetsAgent=China`, `affectsIndustry=Semiconductor` 관계 생성
- 검증 통과 시 자동 accepted

실데이터 검증 결과: 검색 문서 42건 중 정책 Episode 4건 accepted,
pending 0건, critical 0건.

## 남은 작업

1. UCDP 개별 고강도 row를 conflict·dyad·인접 날짜 기준 Episode로 묶는다.
2. 직전 기간 대비 사망자 증가율과 지속 기간을 사용해 Escalation을 판정한다.
3. UCDP dataset release date와 ZIP SHA-256을 snapshot metadata로 저장한다.
4. API/다운로드 체크포인트를 DB에 기록하고 중단 지점부터 재개한다.
5. Federal Register의 발표일과 시행일을 분리한다.
6. 수출통제 완화·해제 및 경제제재·관세·수입제한 규칙을 추가한다.
7. 국가·기관·산업 ID catalog를 팀 ontology IRI와 최종 정렬한다.
8. 팀 백엔드가 읽을 projection/export 계약을 확정한다.

## 현재 제한

- 사망자 25명 기준은 재현 가능한 v1 기준이지만, 모든 행이 실제 “확대”를 뜻하지는 않는다.
- UCDP 과거 버전의 정확한 공개일 metadata가 아직 없어 현재 수집 시각을
  보수적인 public availability로 사용한다.
- UCDP API 증분 실행에는 `UCDP_API_TOKEN`이 필요하다. 공식 ZIP backfill은
  토큰 없이 가능하다.

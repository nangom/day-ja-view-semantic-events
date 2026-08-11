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
- 동일 conflict의 3일 이내 row를 하나의 Episode로 묶는 v2 규칙
- 합산 사망자 25명 이상 + 직전 30일 대비 1.5배 이상일 때 Escalation 판정
- `djv:Escalation`, `occurredIn=MiddleEast` 생성
- `side_a`, `side_b`를 `hasParticipant` 관계로 저장
- UCDP conflict를 `partOfEvent` 관계로 저장
- 발생일과 최초 수집 가능 시각 분리
- UCDP 공식 레코드 URL과 원본 hash를 Evidence로 저장
- dataset version·source URI·입력 hash·coverage·accepted 수 snapshot 저장
- Episode 기간, 사망자, 직전 30일 사망자, 강도 배수 지표 저장
- 같은 입력 재실행 시 중복 삽입 방지

실데이터 검증 결과: GED 26.1 417,968행, accepted Episode 657건,
기간 1989-01-01~2025-12-03, 지표 2,628건, JSONL 657건,
pending 0건, critical 0건.

### Federal Register / 정책·규제

- 공식 API 날짜·검색어·페이지 수집
- raw JSON, document revision, Evidence span과 hash 저장
- 중국 + 반도체 + 수출통제 강화 조건을 모두 만족할 때만
  `djv:ExportControlTightening` 생성
- `targetsAgent=China`, `affectsIndustry=Semiconductor` 관계 생성
- 검증 통과 시 자동 accepted
- 발표일과 시행일(`effective_on`) 분리 저장
- 수출통제 강화·완화와 중국 대상 경제제재 강화 규칙 분리
- 중국 반도체 대상 관세 인상·인하와 수입제한 강화·해제 규칙 분리
- 미국 반도체 보조금 지급·세제혜택 확대 규칙 추가
- 미국 금융시장 규제 강화·완화 규칙 추가
- 공매도 금지·재개와 반도체 투자지원 규칙 분리
- 주제 단어만 있고 정책 방향이 불명확한 문서는 후보에서 제외
- UCDP/Federal Register API 페이지 체크포인트와 `--resume` 지원
- accepted Episode·관계·Evidence·지표의 중립 JSONL export 지원

현재 공식 API 회귀 검증 결과: `semiconductor China` 검색 문서 97건 중
정책 Episode 3건 accepted, JSONL 3건, pending 0건, critical 0건.

전체 단위·통합 테스트 18건 통과.

## 남은 작업

1. 공식 ZIP 다운로드 자체의 byte-range 재개는 서버 지원 여부 확인 후 추가한다.
2. 국가·기관·산업 ID catalog를 팀 ontology IRI와 최종 정렬한다.
3. 중립 JSONL을 팀 백엔드 projection 계약으로 최종 매핑한다.

## 현재 제한

- v2 Escalation 임계값(25명·1.5배·3일·30일)은 재현 가능하지만 제품 calibration이 필요하다.
- UCDP 과거 버전의 정확한 공개일 metadata가 아직 없어 현재 수집 시각을
  보수적인 public availability로 사용한다.
- UCDP API 증분 실행에는 `UCDP_API_TOKEN`이 필요하다. 공식 ZIP backfill은
  토큰 없이 가능하다.
- 새 정책 EventKind 이름은 개인 저장소의 재현 가능한 임시 분류다. 팀 ontology
  IRI가 확정되면 이름만 매핑하고 판별 근거와 원본 hash는 유지한다.

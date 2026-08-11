# Semantic Event 수집 연구 모듈

DAY-JA-VIEW Q2 Core의 시멘틱 조건 가운데 **지정학 사건**과
**정책·규제 사건**의 후보 데이터를 수집한다.

이 모듈은 `origin/codex/overnight-bootstrap`의 2026-08-11 정본을 따른다.
뉴스 기사 DB를 복제하거나 후보를 운영 사건으로 자동 승인하지 않는다.

## 담당 범위

1. 원본 응답과 해시를 불변 저장한다.
2. 원본을 SourceDocument와 EvidenceSpan으로 분리한다.
3. 승인된 MVP 범위에 해당하는 사건 후보만 생성한다.
4. 모든 후보를 `pending` 상태로 review queue에 넣는다.
5. 날짜와 시각의 정밀도를 보존한다.
6. 정정 문서는 이전 문서를 덮어쓰지 않고 `supersedes`로 연결한다.

이 모듈은 accepted KG snapshot과 SQL projection을 만들지 않는다. 운영 publisher는
source 계약 승인, ontology/SHACL 검증, 사람 또는 승인 규칙의 review가 끝난 뒤에만
accepted assertion과 projection을 생성해야 한다.

## Policy/Regulation MVP 범위

- 관세
- 수출통제
- 수입제한
- 산업 보조금
- 세제혜택
- 투자지원
- 금융시장 규제 강화·완화
- 공매도 금지·재개

복지·노동·일반 행정정책은 원본 보관은 가능하지만 사건 후보에서는 제외한다.

## 데이터 흐름

```text
공개 API 응답
→ raw_source_items
→ source_documents
→ evidence_spans
→ deterministic scope rule
→ event_candidates(pending)
→ review_queue
```

## 주요 테이블

- `source_registry`: 제공처의 후보/승인/차단 상태
- `ingestion_runs`: 수집 실행과 건수
- `raw_source_items`: 원본 JSON과 content hash
- `source_documents`: 문서 revision, 공개일, 공식 URL
- `evidence_spans`: JSON Pointer와 해당 값의 hash
- `event_kind_catalog`: 정본 문서에 승인된 EventKind 계층 후보
- `event_candidates`: 아직 분석에 사용할 수 없는 사건 후보
- `event_candidate_relations`: 국가·지역·산업·자산 관계 후보
- `review_queue`: 승인·거절·중복 검수 대기열

## 날짜 원칙

API가 `2026-08-11`만 제공하면 다음처럼 저장한다.

```text
published_on = 2026-08-11
published_at = null
published_precision = day
```

`2026-08-11T00:00:00Z`라는 시각을 임의로 만들지 않는다. 실제 발생 시각,
공개 시각, DAY-JA-VIEW 적재 시각은 서로 다른 필드다.

## 첫 수집기

FederalRegister.gov 공개 API에서 Rule, Proposed Rule, Presidential Document를
가져온다. 검색용 구조화 레코드와 GovInfo 공식 PDF URL을 함께 저장한다.

제공처는 현재 `candidate`, `production_enabled=0`이다. 로컬 연구 수집은 가능하지만
production Q2 Semantic Condition에는 사용할 수 없다.

## 실행

Python 표준 라이브러리만 사용한다.

```powershell
python -m research.semantic_events.cli init
python -m research.semantic_events.cli collect-federal-register `
  --start-date 2026-08-01 --end-date 2026-08-11 --limit 20
python -m research.semantic_events.cli stats
python -m unittest discover research/semantic_events/tests
```

기본 DB는 `research/semantic_events/data/semantic_events.sqlite3`이며 Git에 포함하지
않는다. SQLite는 수집·검수 프로토타입이다. PostgreSQL 정본으로 이전할 때는
`source` 스키마와 review/pending assertion 계층에 매핑한다.

## 인포스탁·퓨리오사 분류와의 연결

인포스탁은 뉴스 원천과 기사 식별자를 제공하고, 퓨리오사에서 실행되는 모델은
기사에서 사건 후보·entity·감성을 추출한다. 이 모듈은 공식 문서와 사건 후보의
기준 레코드를 제공한다.

공통 출력 초안은 `semantic_event_contract.schema.json`, 역할 분리는
`FURIOSA_ALIGNMENT.md`에 기록했다. 실제 팀 모델의 라벨과 인포스탁 필드를 받은 뒤
변환표를 확정한다.

제공처별 용도·접근 조건·승인 전 금지사항은 `SOURCE_PLAN.md`와
`source_plan.json`을 정본으로 사용한다.

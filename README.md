# DAY-JA-VIEW Semantic Events

DAY-JA-VIEW Q2 Core를 위한 지정학·정책/규제 사건 후보 수집 연구 저장소다.

현재 구현 범위:

- Federal Register 공개 API 수집
- 원본 JSON·해시 불변 저장
- SourceDocument·EvidenceSpan 분리
- Policy/Regulation MVP 범위 필터
- pending Event candidate와 review queue 생성
- 날짜 정밀도 및 문서 revision 보존
- SQLite 로컬 프로토타입과 PostgreSQL 이전 고려 스키마

후보 데이터는 자동으로 운영 사건이 되지 않는다. 제공처 계약 승인, Ontology/SHACL
검증과 review를 통과한 사건만 추후 accepted KG와 Q2 검색 Projection에 게시한다.

자세한 설계와 데이터 소스 계획:

- `research/semantic_events/README.md`
- `research/semantic_events/SOURCE_PLAN.md`
- `research/semantic_events/FURIOSA_ALIGNMENT.md`

## 실행

Python 3.11 이상과 표준 라이브러리만 필요하다.

```powershell
python -m research.semantic_events.cli init
python -m research.semantic_events.cli collect-federal-register `
  --start-date 2026-08-01 --end-date 2026-08-11 --limit 20
python -m research.semantic_events.cli stats
python -m unittest discover research/semantic_events/tests
```

기본 SQLite DB는 `research/semantic_events/data/semantic_events.sqlite3`에 생성되며
Git에 포함되지 않는다.


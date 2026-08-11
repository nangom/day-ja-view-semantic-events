# DAY-JA-VIEW Semantic Events

DAY-JA-VIEW Q2 Core를 위한 지정학·정책/규제 사건 후보 수집 연구 저장소다.

현재 구현 범위:

- Federal Register 공개 API 수집
- 원본 JSON·해시 불변 저장
- SourceDocument·EvidenceSpan 분리
- Policy/Regulation MVP 범위 필터
- 검증 통과 Event candidate 자동 accepted, 실패 항목만 review queue 생성
- UCDP GED JSON 기반 중동 무력충돌 확대 Episode 생성
- 날짜 정밀도 및 문서 revision 보존
- SQLite 로컬 프로토타입과 PostgreSQL 이전 고려 스키마

팀의 실데이터 전환 결정 v2.1에 따라 필수 필드·시간·중복·근거 검증을 통과한
사건은 자동 accepted 된다. 검증 실패 항목만 pending으로 남는다.

자세한 설계와 데이터 소스 계획:

- `research/semantic_events/README.md`
- `research/semantic_events/SOURCE_PLAN.md`
- `research/semantic_events/FURIOSA_ALIGNMENT.md`
- `research/semantic_events/HANDOFF_STATUS.md`

## 실행

Python 3.11 이상과 표준 라이브러리만 필요하다.

```powershell
python -m research.semantic_events.cli init
python -m research.semantic_events.cli collect-federal-register `
  --start-date 2026-08-01 --end-date 2026-08-11 --limit 20
python -m research.semantic_events.cli collect-ucdp-api `
  --start-date 1989-01-01 --end-date 2025-12-31 --version 26.1
python -m research.semantic_events.cli collect-ucdp-download
python -m research.semantic_events.cli collect-ucdp-file --input path\to\ucdp-ged.csv
python -m research.semantic_events.cli validate
python -m research.semantic_events.cli stats
python -m unittest discover research/semantic_events/tests
```

기본 SQLite DB는 `research/semantic_events/data/semantic_events.sqlite3`에 생성되며
Git에 포함되지 않는다.

UCDP API 수집은 `UCDP_API_TOKEN` 환경변수가 필요하다. 토큰은 설정 파일이나 DB에
저장하지 않는다. `collect-ucdp-download`는 토큰 없이 UCDP GED 26.1 공식 ZIP을
다운로드하고 스트리밍 처리한다. `collect-ucdp-file`은 이미 받은 공식 CSV를 재사용한다.


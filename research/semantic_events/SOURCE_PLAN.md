# Semantic Event 소스 후보 계획

- 기준: `origin/codex/overnight-bootstrap` 2026-08-11 정본
- 상태: 제공처 승인 전 연구 계획
- 원칙: `candidate` 소스를 production accepted Event에 직접 사용하지 않는다.

## 1. 소스별 역할

| 우선순위 | 영역 | 소스 | 사용 목적 | 현재 조건 |
|---:|---|---|---|---|
| 1 | 미국 정책 | FederalRegister.gov | Rule·Proposed Rule·Presidential Document 검색과 문서번호 | 공개 API, 키 없음. GovInfo 공식 PDF를 함께 보존 |
| 1 | 미국 정책 | GovInfo | Federal Register·법률 문서의 공식 근거 파일 | Bulk 공개. GovInfo API는 api.data.gov 키 필요 |
| 1 | 미국 제재 | OFAC | 제재 지정·변경·해제와 목록 revision | Sanctions List Service 다운로드와 변경 archive 검토 |
| 1 | UN 제재 | UN Security Council | 제재 대상·체제·변경일과 공식 press release | 통합 목록 XML·HTML·PDF와 RSS 제공 |
| 2 | 미국 수출통제 | BIS | EAR·수출통제 설명, 대상 품목·국가 맥락 | BIS 화면은 보조 근거. 법적 문서는 Federal Register/eCFR 연결 |
| 2 | 미국 규제 | Regulations.gov | docket, Proposed Rule→Final Rule 연결, 정정·첨부 | api.data.gov 키 필요 |
| 2 | EU 정책 | EUR-Lex/CELLAR | EU 법령·결정·규정 원문과 CELEX revision | 검색 웹서비스 등록 필요. 대량은 CELLAR 또는 dump |
| 2 | 지정학 | UCDP GED | 무력충돌 발생 위치·참여자·날짜 후보 | 무료지만 access token 요청 필요, version 필수 |
| 보류 | 지정학 | ACLED | 충돌·시위·전략적 사건 Episode 후보 | OAuth와 조직 유형별 라이선스 승인 전 사용 금지 |
| 보조 | 발견 | GDELT 2.0 | 다국어 뉴스 기반 사건 탐색과 교차검증 후보 | 단독으로 accepted Event 생성 금지 |

## 2. 사건별 조합

### 정책·규제

```text
FederalRegister.gov metadata
+ GovInfo official document
+ BIS/OFAC/Regulations.gov/EUR-Lex의 기관별 세부 근거
→ pending Policy Event candidate
```

### 지정학 무력충돌

```text
UCDP 또는 승인된 ACLED event row
+ UN·정부 공식 발표
+ GDELT/뉴스의 교차검증 후보
→ pending Geopolitical Episode candidate
```

### 경제제재

```text
OFAC 또는 UN Security Council의 목록 변경·공식 발표
+ 관련 법령·결정 문서
→ pending EconomicSanction Episode candidate
```

## 3. 소스별 금지사항

- GDELT 기사 건수를 실제 사건 건수로 사용하지 않는다.
- 인포스탁 기사와 모델 분류만으로 accepted Event를 만들지 않는다.
- ACLED 원시 데이터를 라이선스 승인 없이 저장·재배포하지 않는다.
- FederalRegister.gov 구조화 화면만 법적 공식판으로 표시하지 않는다.
- UN·OFAC 현재 목록을 과거 시점 목록으로 역산하지 않는다. archive·delta를 사용한다.
- 정책 발표일과 시행일을 같은 날짜로 강제하지 않는다.

## 4. 구현 순서

1. Federal Register 원본→문서→근거→pending 후보 파이프라인
2. OFAC·UN 제재 revision 수집기
3. Regulations.gov docket 연결기
4. EUR-Lex 접근 등록 후 EU 정책 수집기
5. UCDP token 확보 후 무력충돌 후보 수집기
6. Episode dedupe review와 accepted KG publisher 연동

## 5. 팀 확인이 필요한 결정

1. 각 제공처의 저장·재배포·상업적 이용 가능 범위
2. 인포스탁 `article_id`, 게시시각, 종목·테마 필드 사양
3. 퓨리오사 실행 모델의 EventKind·entity·confidence 출력 형식
4. accepted 자동 승인 가능 source와 반드시 사람 검수가 필요한 source
5. UCDP token 신청 주체와 ACLED 조직 라이선스 사용 여부


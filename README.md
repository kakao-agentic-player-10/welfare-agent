# Welfare Agent

복지/지원금 후보를 로컬 SQLite + sqlite-vec 인덱스에서 검색하는 PlayMCP용 MCP 서버입니다.

현재 설계는 “신청 가능성 높은 후보를 빠르게 찾고, 최종 세부 조건은 사용자가 공식 링크에서 확인”하는 방향입니다. 서버는 나이와 지역을 중심으로 필터링하며, 소득/가구원 범위/중복 지원 제한/제출서류는 별도 DB 컬럼이나 tool로 관리하지 않습니다.

## 데이터 소스

현재 사용하는 OpenAPI 소스는 2개입니다.

- `public_service_benefits`
- `youth_policy`

MCP 요청 중에는 OpenAPI를 직접 호출하지 않습니다. 먼저 데이터를 동기화하고 임베딩을 저장한 뒤, 검색 요청은 로컬 DB만 조회합니다.

## 필요한 키

### 공공데이터포털

```text
DATA_GO_KR_SERVICE_KEY=
PUBLIC_SERVICE_API_URL=
YOUTH_POLICY_API_KEY=
YOUTH_POLICY_API_URL=
```

### OpenAI Embeddings

벡터 검색에 필요합니다.

```text
OPENAI_API_KEY=
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=1536
```

### Kakao Local

`find_visit_offices`에서 방문 기관 위치 검색에만 사용합니다.

```text
KAKAO_REST_API_KEY=
```

일정 등록 기능은 사용하지 않습니다.

## 실행

```bash
uv sync
uv run python main.py
```

로컬 MCP endpoint:

```text
http://127.0.0.1:8000/mcp
```

## 동기화

```bash
PYTHONPATH=src uv run python scripts/sync_benefits.py --mode full
PYTHONPATH=src uv run python scripts/enrich_public_service_conditions.py --request-limit 8000 --limit 8000
```

운영에서는 서버 프로세스 내부 스케줄러가 시작 시 1회 동기화하고, 이후 매일 03:30 KST에 증분 동기화합니다.
목록 동기화가 끝나면 `public_service_benefits` 중 아직 `supportConditions`가 없는 항목을 이어서 보강합니다.

스케줄러 보강 설정:

```text
WELFARE_SUPPORT_CONDITIONS_ENABLED=true
WELFARE_SUPPORT_CONDITIONS_REQUEST_LIMIT=8000
WELFARE_SUPPORT_CONDITIONS_LIMIT=8000
WELFARE_SUPPORT_CONDITIONS_BATCH_SIZE=100
```

`enrichment_checkpoints`의 cursor 기준으로 이어받기 때문에 DB를 삭제하지 않으면 다음 실행은 남은 항목부터 처리합니다.

## MCP Tools

- `save_profile`: 자연어/필드 입력을 검색용 프로필로 구조화
- `search_benefits`: SQLite/sqlite-vec 인덱스에서 후보 검색
- `match_benefits`: 검색 결과를 profile 기준으로 재정렬
- `find_visit_offices`: Kakao Local로 방문 기관 검색

## 필터 정책

Hard filter:

- 지역
- 나이
- 공식 필드 기준 명확히 마감된 신청기간

Ranking signal:

- 벡터 유사도
- 대상 유형
- 관심사
- 주거/취업/가구 형태 키워드
- `supportConditions` 대상 플래그

별도 필터/응답 필드로 관리하지 않는 정보:

- 소득
- 가구원 범위
- 중복 지원 제한
- 제출서류

## 검증

```bash
PYTHONPATH=src uv run ruff check src tests scripts
PYTHONPATH=src uv run pytest
PYTHONPATH=src uv run python -m compileall main.py src scripts tests
WELFARE_SYNC_ENABLED=false PYTHONPATH=src uv run python -c "from welfare_agent.server import create_server; create_server(); print('server ok')"
```

AI가 tool call을 선택하는 흐름을 로컬에서 테스트하려면:

```bash
PYTHONPATH=src uv run python scripts/prompt_ai_mcp.py \
  --prompt "서울 관악구 월세 원룸에 혼자 사는 27세 취업준비생이야. 받을 수 있는 복지 알려줘"
```

MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
```

Transport는 `Streamable HTTP`, URL은 `http://127.0.0.1:8000/mcp`를 사용합니다.

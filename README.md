# BenefitScout (혜택탐정)

공공 복지/지원금 후보를 로컬 SQLite + sqlite-vec 인덱스에서 검색하는 PlayMCP용 MCP 서버입니다.

신청 가능성 높은 후보를 빠르게 찾고, 최종 세부 조건은 사용자가 공식 링크에서 확인하는 방향으로 설계되어 있습니다.

## MCP Tools

| Tool | 설명 |
|---|---|
| `save_profile` | 자연어/필드 입력을 검색용 프로필로 구조화 — 항상 첫 번째로 호출 |
| `search_benefits` | 프로필 기반 벡터 검색으로 복지 DB에서 후보 탐색 |
| `match_benefits` | 검색 결과를 나이·지역·가구유형 적합성으로 재정렬, 상위 10개 반환 |
| `find_visit_offices` | Kakao Local API로 방문 신청 기관(주민센터 등) 검색 |

## 데이터 소스

- `public_service_benefits` (공공데이터포털 gov24)
- `youth_policy` (청년정책 youthcenter)

MCP 요청 중 외부 API를 직접 호출하지 않습니다. 미리 동기화·임베딩된 로컬 DB만 조회합니다.

## 배포 (PlayMCP in KC)

Git 소스 빌드로 배포합니다. Dockerfile이 빌드 시 GitHub Releases에서 DB를 자동 다운로드해 이미지에 포함시킵니다.

**환경변수 설정**

| 키 | 설명 |
|---|---|
| `OPENAI_API_KEY` | 벡터 검색용 임베딩. `OPENAI_EMBEDDING_PROXY_URL`을 쓰지 않을 때 필요 |
| `OPENAI_EMBEDDING_PROXY_URL` | OpenAI 키를 런타임에 넣을 수 없는 배포 환경에서 사용할 임베딩 프록시 URL |
| `OPENAI_EMBEDDING_PROXY_TOKEN` | 임베딩 프록시 인증 토큰. 런타임 환경변수로만 설정하고 Dockerfile/레포에는 넣지 않음 |
| `DATA_GO_KR_SERVICE_KEY` | 공공데이터포털 서비스키 |
| `YOUTH_POLICY_API_KEY` | 청년정책 API 키 |
| `KAKAO_REST_API_KEY` | 방문 기관 위치 검색 |
| `PUBLIC_SERVICE_API_URL` | `https://api.odcloud.kr/api/gov24/v3/serviceList` |
| `YOUTH_POLICY_API_URL` | `https://www.youthcenter.go.kr/go/ythip/getPlcy` |

`OPENAI_API_KEY`와 `OPENAI_EMBEDDING_PROXY_TOKEN`은 Dockerfile, GitHub, 공개 문서에 넣지 않습니다.
PlayMCP in KC처럼 런타임 환경변수 입력이 어려운 경우 별도 임베딩 프록시에 OpenAI 키를 보관하고,
이 서버에는 공개 가능한 `OPENAI_EMBEDDING_PROXY_URL`만 설정합니다.

현재 PlayMCP in KC 배포용 기본 프록시 URL:

```text
https://playmcp-embedding-proxy.onrender.com/v1/embeddings
```

프록시는 OpenAI Embeddings API와 같은 형식의 요청을 받을 수 있어야 합니다.

```json
{
  "model": "text-embedding-3-small",
  "input": ["청년 월세 지원"],
  "dimensions": 1536
}
```

응답은 OpenAI 호환 형식 또는 간단한 `embeddings` 배열을 지원합니다.

```json
{"data":[{"embedding":[0.1,0.2]}]}
```

```json
{"embeddings":[[0.1,0.2]]}
```

## 로컬 실행

```bash
cp .env.example .env  # 키 값 채우기
uv sync
uv run python main.py
```

MCP endpoint: `http://127.0.0.1:8000/mcp`

## DB 동기화

서버 기동 시 자동 동기화(`WELFARE_SYNC_ON_STARTUP=true`)되며, 이후 매일 03:30 KST에 증분 동기화합니다.

## 필터 정책

**Hard filter** (검색 전 제외): 지역, 나이, 공식 마감된 신청기간

**Ranking signal** (재정렬 기준): 벡터 유사도, 대상 유형, 관심사, 주거/취업/가구 형태, supportConditions 플래그

별도로 관리하지 않는 정보: 소득, 가구원 범위, 중복 지원 제한, 제출서류

## 검증

```bash
PYTHONPATH=src uv run ruff check src
WELFARE_SYNC_ENABLED=false PYTHONPATH=src uv run python -c "from welfare_agent.server import create_server; create_server(); print('ok')"
```

MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP / URL: http://127.0.0.1:8000/mcp
```

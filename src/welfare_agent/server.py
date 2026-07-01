from __future__ import annotations

from typing import Any
import logging

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from welfare_agent.clients import (
    ExternalApiError,
    KakaoLocalClient,
)
from welfare_agent.config import load_settings
from welfare_agent.domain import (
    benefit_search_keyword,
    build_profile,
    filter_region_applicable,
    filter_age_applicable,
    filter_target_applicable,
    match_benefits as rank_benefits,
    region_scope_info,
    today_kst,
)
from welfare_agent.clients.embeddings import EmbeddingConfig, OpenAIEmbeddingClient
from welfare_agent.ingestion.scheduler import start_background_sync
from welfare_agent.store import BenefitStore


logger = logging.getLogger(__name__)
MAX_USER_BENEFIT_RESULTS = 10
MAX_SEARCH_CANDIDATES = 30


# FastMCP 서버를 만들고 PlayMCP에 노출할 도구들을 등록한다.
def create_server() -> FastMCP:
    settings = load_settings()
    benefit_store = BenefitStore(
        settings.sqlite_path,
        vector_dimensions=settings.openai_embedding_dimensions,
    )
    embeddings = OpenAIEmbeddingClient(
        EmbeddingConfig(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
            proxy_url=settings.openai_embedding_proxy_url,
            proxy_token=settings.openai_embedding_proxy_token,
            timeout_seconds=settings.openai_embedding_proxy_timeout_seconds,
        )
    )
    local = KakaoLocalClient(settings.kakao_rest_api_key)
    mcp = FastMCP("BenefitScout")
    start_background_sync(settings)

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "BenefitScout"})

    # 사용자 조건을 구조화된 프로필로 정규화한다.
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Save Benefit Profile",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def save_profile(
        text: str = "",
        age: int | None = None,
        region: str = "",
        household_type: str = "",
        employment_status: str = "",
        housing_type: str = "",
        marital_status: str = "",
        business_type: str = "",
        revenue_status: str = "",
        interests: list[str] | None = None,
    ) -> dict[str, Any]:
        """[Step 1/3] Build a structured eligibility profile for BenefitScout(혜택탐정). Call this FIRST when a user asks about government welfare benefits, subsidies, or support programs. Pass the returned profile dict to search_benefits() and match_benefits(). Omit unknown fields rather than guessing. text=free-form Korean description of the user's situation e.g. "취업준비 중인 28살 대구 청년, 월세 거주"; age=age in years; region=시도 e.g. "서울"|"경기" or 시군구 e.g. "강남구"|"수원시"; household_type=1인가구|한부모|신혼부부|조손가구|다자녀|일반가구; employment_status=취업준비생|재직자|구직자|자영업자|프리랜서|무직|퇴직자; housing_type=월세|전세|자가|무주택|공공임대; marital_status=미혼|기혼|이혼|사별; business_type=e.g. 소상공인|개인사업자; revenue_status=e.g. 저소득|중위소득 80% 이하|기초생활수급; interests=category keywords e.g. ["주거","교육","청년","취업","의료"]. Returns {"profile":{...}}."""
        profile = build_profile(
            text=text,
            age=age,
            region=region,
            household_type=household_type,
            employment_status=employment_status,
            housing_type=housing_type,
            marital_status=marital_status,
            business_type=business_type,
            revenue_status=revenue_status,
            interests=interests,
        )
        return {"profile": profile}

    # 프로필 기반 임베딩으로 사전 색인된 지원사업 후보를 검색한다.
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Search Benefit Programs",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def search_benefits(
        profile: dict[str, Any],
        keyword: str = "",
        size: int = MAX_SEARCH_CANDIDATES,
        available_only: bool | None = True,
        as_of_date: str = "",
        include_unknown_periods: bool | None = True,
        exclude_definitely_closed: bool | None = True,
        strict: bool | None = False,
    ) -> dict[str, Any]:
        """[Step 2/3] Search the BenefitScout(혜택탐정) welfare benefit database using the profile from save_profile(). Call AFTER save_profile(); pass profile["profile"] as the profile argument. Uses vector similarity search on pre-indexed Korean public benefit programs. profile=required dict from save_profile()["profile"]; keyword=optional search term to focus results, leave empty to auto-generate from profile e.g. "청년 월세"|"임산부 지원"; size=max results 1-30 default 30; available_only=true skips officially closed programs (default true); include_unknown_periods=true includes programs with unannounced periods (default true); exclude_definitely_closed=true excludes confirmed closed (default true); strict=true gates on profile completeness, returns needs_input+required_fields if missing (default false); as_of_date=YYYY-MM-DD reference date, defaults to today KST. Returns {"ok":true,"items":[...],"result_count":N}; pass items to match_benefits() as the benefits parameter."""
        available_only = True if available_only is None else bool(available_only)
        include_unknown_periods = True if include_unknown_periods is None else bool(include_unknown_periods)
        exclude_definitely_closed = (
            True if exclude_definitely_closed is None else bool(exclude_definitely_closed)
        )
        gate = strict_search_gate(profile, strict=bool(strict))
        if gate:
            return gate
        query = benefit_search_keyword(profile, keyword)
        result_limit = clamp_search_size(size)
        period_filter_enabled = bool(available_only and exclude_definitely_closed)
        available_on = (as_of_date or today_kst()) if period_filter_enabled else None

        if not embeddings.config.ready:
            return {
                "ok": False,
                "query": query,
                "items": [],
                "message": (
                    "OPENAI_API_KEY 또는 OPENAI_EMBEDDING_PROXY_URL이 필요합니다. "
                    "임베딩 기반 검색을 사용하려면 직접 OpenAI 키를 설정하거나 임베딩 프록시를 설정하세요."
                ),
            }

        active_count = benefit_store.count_active()
        if active_count == 0:
            return {
                "ok": False,
                "query": query,
                "items": [],
                "message": "로컬 복지 DB가 비어 있습니다. `uv run python scripts/sync_benefits.py`로 OpenAPI 데이터를 먼저 동기화하세요.",
            }

        try:
            query_embedding = embeddings.embed_one(query)
            if not query_embedding:
                return {"ok": False, "query": query, "items": [], "message": "임베딩 생성에 실패했습니다."}
            fetched_count = 0
            candidates = []
            for fetch_limit in search_fetch_limits(result_limit, profile):
                items = benefit_store.search(
                    embedding=query_embedding,
                    limit=fetch_limit,
                    available_on=available_on,
                    include_unknown_periods=include_unknown_periods,
                )
                fetched_count = len(items)
                candidates = filter_target_applicable(
                    profile,
                    filter_age_applicable(profile, filter_region_applicable(profile, items)),
                )
                if len(candidates) >= result_limit or fetched_count < fetch_limit:
                    break
            ranked_candidates = rank_benefits(profile, candidates)[:result_limit]
            items = [
                with_search_match_metadata(profile, match)
                for match in ranked_candidates
            ]
            items = [to_search_item(item) for item in items]
        except ExternalApiError as exc:
            return {"ok": False, "error": str(exc), "items": []}
        except Exception as exc:
            return {"ok": False, "error": f"복지 DB 검색 실패: {exc}", "items": []}

        return {
            "ok": True,
            "query": query,
            "items": items,
            "result_count": len(items),
            "fetched_count": fetched_count,
            "index_count": active_count,
            "available_only": available_only,
            "exclude_definitely_closed": exclude_definitely_closed,
            "period_filter_policy": "exclude_only_officially_closed",
            "as_of_date": available_on,
            "include_unknown_periods": include_unknown_periods,
            "requested_size": size,
            "max_size": MAX_SEARCH_CANDIDATES,
        }

    # 검색 결과와 사용자 프로필을 비교해 가능성 순으로 정렬한다.
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Match Benefit Eligibility",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def match_benefits(profile: dict[str, Any], benefits: list[dict[str, Any]]) -> dict[str, Any]:
        """[Step 3/3] Re-rank BenefitScout(혜택탐정) benefit candidates by eligibility likelihood and return the final list to show the user. Call AFTER search_benefits(). Re-ranks by age range, region match, household type, and target group signals beyond vector similarity. profile=same profile dict from save_profile(); benefits=items list from search_benefits()["items"], pass as-is without modification. Returns {"matches":[...],"matched_count":N,"disclaimer":"..."} with up to 10 programs sorted by likelihood (high>medium>low). Each match includes likelihood, match_score, matched_reasons, and full benefit details. ALWAYS show the disclaimer text verbatim when presenting results to the user. Likelihood scores indicate relevance, NOT confirmed eligibility — advise users to verify with the official organization."""
        matches = rank_benefits(profile, benefits)[:MAX_USER_BENEFIT_RESULTS]
        input_count = len(benefits)
        matched_count = len(matches)
        return {
            "matches": [
                {**match, "benefit": to_search_item(match["benefit"])}
                for match in matches
            ],
            "input_count": input_count,
            "matched_count": matched_count,
            "message": (
                "benefits 입력이 비어 있습니다. search_benefits 응답의 items 배열을 benefits에 넣어야 합니다."
                if input_count == 0 else ""
            ),
            "disclaimer": "수급 가능 여부를 확정하지 않으며, 최종 자격은 공고문/기관 기준 확인이 필요합니다.",
            "max_size": MAX_USER_BENEFIT_RESULTS,
        }

    # Kakao Local API로 방문 가능한 기관/센터를 검색한다.
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Find Visit Offices",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    def find_visit_offices(query: str, x: str = "", y: str = "") -> dict[str, Any]:
        """Find nearby public offices or welfare centers for in-person benefit applications in BenefitScout(혜택탐정). Call when the user asks where to apply in person, or when a benefit's application_method contains "방문 신청" or "주민센터 방문". Uses Kakao Local API for real-time location search. query=Korean office type e.g. "주민센터","행정복지센터","복지관","고용복지플러스센터","청년센터"; append region for locality e.g. "강남구 주민센터","수원시 고용센터". x=longitude WGS84 decimal string e.g. "127.0276" (optional); y=latitude WGS84 decimal string e.g. "37.4979" (optional); omit x and y if user location is unknown. Returns {"ok":true,"places":[...]} with name, address, phone, and map URL per place. Returns {"ok":false,"error":"..."} if Kakao API is unavailable."""
        try:
            return local.keyword_search(query=query, x=x, y=y)
        except ExternalApiError as exc:
            return {"ok": False, "error": str(exc), "places": []}

    return mcp


def clamp_search_size(size: int) -> int:
    return max(1, min(size, MAX_SEARCH_CANDIDATES))


def strict_search_gate(profile: dict[str, Any], *, strict: bool = False) -> dict[str, Any] | None:
    strict = bool(strict or profile.get("strict_eligibility_requested"))
    missing = profile.get("missing_for_confidence", [])
    if not strict or not missing:
        return None
    return {
        "ok": False,
        "needs_input": True,
        "query": "",
        "items": [],
        "message": "신청 가능한 복지만 추천하려면 추가 정보가 필요합니다.",
        "required_fields": missing,
        "questions": profile.get("follow_up_questions", []),
    }


def search_fetch_limit(result_limit: int, profile: dict[str, Any]) -> int:
    if profile.get("region") or profile.get("text"):
        return min(max(result_limit * 5, 50), 150)
    return result_limit


def search_fetch_limits(result_limit: int, profile: dict[str, Any]) -> list[int]:
    first = search_fetch_limit(result_limit, profile)
    if not (profile.get("region") or profile.get("text")):
        return [first]
    limits = [first, max(first, 150), max(first, 300)]
    deduped: list[int] = []
    for limit in limits:
        if limit not in deduped:
            deduped.append(limit)
    return deduped


def with_region_scope(profile: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {**item, **region_scope_info(profile, item)}


def with_search_match_metadata(profile: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    item = with_region_scope(profile, match["benefit"])
    return {
        **item,
        "likelihood": match["likelihood"],
        "match_score": match["score"],
        "matched_reasons": match["matched_reasons"],
    }


# 검색/매칭 결과를 사용자 표시에 필요한 상세 필드까지 포함해 정리한다.
def to_search_item(item: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "id": item.get("id"),
        "source": item.get("source"),
        "external_id": item.get("external_id"),
        "title": item.get("title", ""),
        "summary": truncate_text(item.get("summary", ""), 600),
        "target": truncate_text(item.get("target", ""), 600),
        "criteria": truncate_text(item.get("criteria", ""), 600),
        "content": truncate_text(item.get("content", ""), 1200),
        "category": item.get("category", ""),
        "application_period": item.get("application_period", ""),
        "business_period": item.get("business_period", ""),
        "application_status": item.get("application_status", ""),
        "period_status": item.get("period_status", ""),
        "period_parse_status": item.get("period_parse_status", ""),
        "period_source": item.get("period_source", ""),
        "period_start_date": item.get("period_start_date", ""),
        "period_end_date": item.get("period_end_date", ""),
        "period_can_exclude": item.get("period_can_exclude", False),
        "period_reason": item.get("period_reason", ""),
        "application_method": truncate_text(item.get("application_method", ""), 400),
        "organization": item.get("organization", ""),
        "contact": truncate_text(item.get("contact", ""), 200),
        "url": item.get("url", ""),
        "application_url": item.get("application_url", ""),
        "extra_urls": item.get("extra_urls", ""),
        "region_sido": item.get("region_sido", ""),
        "region_sigungu": item.get("region_sigungu", ""),
        "age_min": item.get("age_min", ""),
        "age_max": item.get("age_max", ""),
        "region_scope": item.get("region_scope", ""),
        "region_scope_reason": item.get("region_scope_reason", ""),
        "likelihood": item.get("likelihood", ""),
        "match_score": item.get("match_score", ""),
        "matched_reasons": item.get("matched_reasons", []),
    }
    if "vector_distance" in item:
        compact["vector_distance"] = item["vector_distance"]
    return compact


def truncate_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"

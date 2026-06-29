from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice
import time
import uuid
from typing import Any, Callable, Iterable

from welfare_agent.config import Settings
from welfare_agent.clients.embeddings import EmbeddingConfig, OpenAIEmbeddingClient
from welfare_agent.ingestion import PublicServiceClient, build_sources
from welfare_agent.store import (
    BenefitStore,
    benefit_content_hash,
    benefit_external_id,
    benefit_search_text,
    utc_now,
)


@dataclass(frozen=True)
class SyncOptions:
    page_size: int = 100
    max_pages: int = 200
    batch_size: int = 64
    sources: tuple[str, ...] = ()
    mode: str = "auto"
    deactivate_missing: bool = False
    unchanged_stop_count: int | None = None
    lock_ttl_seconds: int = 21600


@dataclass
class SourceSyncSummary:
    source: str
    mode: str
    pages: int = 0
    saved: int = 0
    changed: int = 0
    unchanged: int = 0
    skipped: int = 0
    deactivated: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SyncResult:
    total_saved: int = 0
    active_count: int = 0
    sources: list[SourceSyncSummary] = field(default_factory=list)


def options_from_settings(settings: Settings) -> SyncOptions:
    return SyncOptions(
        page_size=settings.sync_page_size,
        max_pages=settings.sync_max_pages,
        batch_size=settings.sync_batch_size,
        mode=settings.sync_mode,
    )


def sync_benefits(
    settings: Settings,
    options: SyncOptions | None = None,
    *,
    log: Callable[[str], None] = print,
) -> SyncResult:
    options = options or options_from_settings(settings)
    store = BenefitStore(settings.sqlite_path, settings.openai_embedding_dimensions)
    lock_owner = f"welfare-sync-{uuid.uuid4()}"
    if not store.acquire_sync_lock("benefit-sync", owner=lock_owner, ttl_seconds=options.lock_ttl_seconds):
        log("[SKIP] benefit sync is already running")
        return SyncResult(active_count=store.count_active())

    embeddings = OpenAIEmbeddingClient(
        EmbeddingConfig(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
        )
    )
    configs = [config for config in build_sources(settings) if config.ready]
    if options.sources:
        wanted = set(options.sources)
        configs = [config for config in configs if config.name in wanted]

    try:
        sync_started_at = utc_now()
        result = SyncResult()
        for config in configs:
            source_mode = resolve_source_mode(store, config.name, options.mode)
            summary = SourceSyncSummary(source=config.name, mode=source_mode)
            client = PublicServiceClient([config])
            unchanged_streak = 0
            stop_after = options.unchanged_stop_count or options.page_size

            log(f"[SYNC] {config.name} mode={source_mode}")
            for page in range(1, options.max_pages + 1):
                response = fetch_page_with_retry(client, page, options.page_size, log=log)
                summary.pages += 1
                if response.get("errors"):
                    summary.errors.extend(response["errors"])
                    log(f"  [WARN] page={page} errors={response['errors']}")

                items = response.get("items", [])
                if not items:
                    # 재시도 후에도 비어 있으면 데이터 끝으로 간주한다.
                    log(f"  [DONE] page={page} empty (retries exhausted)")
                    break

                page_result = save_items(
                    store,
                    embeddings,
                    config.name,
                    items,
                    batch_size=options.batch_size,
                    incremental=source_mode == "incremental",
                    touch_unchanged=options.deactivate_missing and source_mode == "full",
                )
                summary.saved += page_result["saved"]
                summary.changed += page_result["changed"]
                summary.unchanged += page_result["unchanged"]
                summary.skipped += page_result["skipped"]
                result.total_saved += page_result["saved"]

                if source_mode == "incremental":
                    unchanged_streak += page_result["trailing_unchanged"]
                    if page_result["changed"]:
                        unchanged_streak = page_result["trailing_unchanged"]

                log(
                    "  [ OK ] "
                    f"page={page} saved={page_result['saved']} "
                    f"changed={page_result['changed']} unchanged={page_result['unchanged']}"
                )

                if len(items) < options.page_size:
                    break
                if source_mode == "incremental" and unchanged_streak >= stop_after:
                    log(f"  [STOP] unchanged_streak={unchanged_streak}")
                    break

            if options.deactivate_missing and source_mode == "full":
                summary.deactivated = store.mark_source_inactive_if_stale(config.name, sync_started_at)
                log(f"  [STALE] deactivated={summary.deactivated}")

            log(f"  [SUM] source_saved={summary.saved}")
            result.sources.append(summary)

        result.active_count = store.count_active()
        log(f"[DONE] total_saved={result.total_saved}, active_count={result.active_count}")
        return result
    finally:
        store.release_sync_lock("benefit-sync", owner=lock_owner)


# 페이지 응답이 비면 일시적 오류/레이트리밋일 수 있어 짧게 재시도한 뒤 결과를 돌려준다.
# (한 페이지의 일시 오류로 소스 전체가 잘리는 것을 막는다.)
def fetch_page_with_retry(
    client: PublicServiceClient,
    page: int,
    size: int,
    *,
    retries: int = 3,
    backoff_seconds: float = 2.0,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    response = client.search(page=page, size=size)
    attempt = 0
    while not response.get("items") and attempt < retries:
        attempt += 1
        log(f"  [RETRY] page={page} empty (attempt {attempt}/{retries})")
        time.sleep(backoff_seconds * attempt)
        response = client.search(page=page, size=size)
    return response


def resolve_source_mode(store: BenefitStore, source: str, requested_mode: str) -> str:
    if requested_mode == "full":
        return "full"
    if requested_mode == "incremental":
        return "incremental"
    return "full" if store.count_source(source) == 0 else "incremental"


def save_items(
    store: BenefitStore,
    embeddings: OpenAIEmbeddingClient,
    source: str,
    items: list[dict],
    *,
    batch_size: int,
    incremental: bool,
    touch_unchanged: bool = False,
) -> dict[str, int]:
    result = {"saved": 0, "changed": 0, "unchanged": 0, "skipped": 0, "trailing_unchanged": 0}
    for batch in chunks(items, batch_size):
        pending: list[dict] = []
        for item in batch:
            external_id = benefit_external_id(item)
            content_hash = benefit_content_hash(item, source=source)
            state = store.get_benefit_state(source, external_id)
            unchanged = bool(
                incremental and state and state["active"] and state["content_hash"] == content_hash
            )
            if unchanged:
                result["unchanged"] += 1
                result["trailing_unchanged"] += 1
                if touch_unchanged:
                    store.upsert_benefit(item, source=source)
                    result["saved"] += 1
                else:
                    result["skipped"] += 1
                continue

            result["changed"] += 1
            result["trailing_unchanged"] = 0
            pending.append(item)

        if not pending:
            continue

        texts = [benefit_search_text(item) for item in pending]
        vectors = embeddings.embed_many(texts) if embeddings.config.ready else []
        for index, item in enumerate(pending):
            vector = vectors[index] if index < len(vectors) else None
            store.upsert_benefit(item, source=source, embedding=vector)
            result["saved"] += 1

    return result


def chunks(items: list[dict], size: int) -> Iterable[list[dict]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch

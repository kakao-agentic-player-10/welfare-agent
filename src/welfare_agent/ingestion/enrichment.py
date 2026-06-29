from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import uuid

import httpx

from welfare_agent.config import Settings
from welfare_agent.ingestion.http import extract_items, parse_response_payload
from welfare_agent.store import BenefitStore


CHECKPOINT_NAME = "public_service_benefits:supportConditions"
LOCK_NAME = "support-conditions-enrichment"


@dataclass(frozen=True)
class EnrichmentOptions:
    limit: int = 500
    request_limit: int = 500
    batch_size: int = 100
    reset: bool = False
    quiet: bool = False
    dry_run: bool = False
    lock_ttl_seconds: int = 21600


@dataclass
class EnrichmentResult:
    inspected: int = 0
    enriched: int = 0
    request_count: int = 0
    total_request_count: int = 0
    cursor: int = 0
    status: str = "idle"


def enrichment_options_from_settings(settings: Settings) -> EnrichmentOptions:
    return EnrichmentOptions(
        limit=settings.support_conditions_enrichment_limit,
        request_limit=settings.support_conditions_enrichment_request_limit,
        batch_size=settings.support_conditions_enrichment_batch_size,
    )


def enrich_public_service_conditions(
    settings: Settings,
    options: EnrichmentOptions | None = None,
    *,
    log: Callable[[str], None] = print,
) -> EnrichmentResult:
    options = options or enrichment_options_from_settings(settings)
    endpoint = support_conditions_endpoint(settings.public_service_api_url)
    if not settings.support_conditions_enrichment_enabled:
        log("[SKIP] supportConditions enrichment is disabled")
        return EnrichmentResult(status="skipped")
    if not endpoint or not settings.data_go_kr_service_key:
        log("[SKIP] supportConditions enrichment endpoint or service key is missing")
        return EnrichmentResult(status="skipped")

    store = BenefitStore(settings.sqlite_path, settings.openai_embedding_dimensions)
    lock_owner = f"support-conditions-{uuid.uuid4()}"
    if not store.acquire_sync_lock(LOCK_NAME, owner=lock_owner, ttl_seconds=options.lock_ttl_seconds):
        log("[SKIP] supportConditions enrichment is already running")
        return EnrichmentResult(status="skipped")

    try:
        return _run_enrichment(store, settings, endpoint, options, log=log)
    finally:
        store.release_sync_lock(LOCK_NAME, owner=lock_owner)


def _run_enrichment(
    store: BenefitStore,
    settings: Settings,
    endpoint: str,
    options: EnrichmentOptions,
    *,
    log: Callable[[str], None],
) -> EnrichmentResult:
    checkpoint = store.get_enrichment_checkpoint(CHECKPOINT_NAME)
    after_id = 0 if options.reset or not checkpoint else int(checkpoint.get("cursor") or 0)
    previous_request_count = (
        0 if options.reset or not checkpoint else int(checkpoint.get("request_count") or 0)
    )
    run_request_count = 0
    inspected = 0
    enriched = 0
    last_id = after_id
    result = EnrichmentResult(cursor=last_id, status="running")

    if not options.dry_run:
        store.update_enrichment_checkpoint(
            CHECKPOINT_NAME,
            endpoint=endpoint,
            cursor=str(after_id),
            request_count=previous_request_count,
            status="running",
        )

    try:
        with httpx.Client(timeout=15) as client:
            while inspected < options.limit and run_request_count < options.request_limit:
                batch_limit = min(
                    options.batch_size,
                    options.limit - inspected,
                    options.request_limit - run_request_count,
                )
                benefits = store.list_public_service_ids_for_enrichment(
                    after_id=last_id,
                    limit=batch_limit,
                    missing_only=True,
                )
                if not benefits:
                    result.status = "complete"
                    if not options.dry_run:
                        store.update_enrichment_checkpoint(
                            CHECKPOINT_NAME,
                            endpoint=endpoint,
                            cursor=str(last_id),
                            request_count=previous_request_count + run_request_count,
                            status=result.status,
                        )
                    break

                for benefit in benefits:
                    inspected += 1
                    benefit_id = int(benefit["id"])
                    if options.dry_run:
                        log(
                            f"[DRY] id={benefit['id']} "
                            f"service={benefit['external_id']} {benefit['title']}"
                        )
                        last_id = benefit_id
                        continue

                    item = fetch_support_conditions(
                        client,
                        endpoint=endpoint,
                        service_key=settings.data_go_kr_service_key,
                        service_id=str(benefit["external_id"]),
                    )
                    run_request_count += 1
                    total_request_count = previous_request_count + run_request_count
                    store.upsert_support_conditions(benefit_id, item)
                    if item:
                        enriched += 1
                    if not options.quiet:
                        conditions_status = "yes" if item else "empty"
                        log(
                            f"[OK] id={benefit['id']} request_count={total_request_count} "
                            f"enriched={enriched} conditions={conditions_status} title={benefit['title']}"
                        )

                    last_id = benefit_id
                    store.update_enrichment_checkpoint(
                        CHECKPOINT_NAME,
                        endpoint=endpoint,
                        cursor=str(last_id),
                        request_count=total_request_count,
                        status="running",
                    )

            if result.status != "complete":
                result.status = "paused" if run_request_count >= options.request_limit else "complete"
                if not options.dry_run:
                    store.update_enrichment_checkpoint(
                        CHECKPOINT_NAME,
                        endpoint=endpoint,
                        cursor=str(last_id),
                        request_count=previous_request_count + run_request_count,
                        status=result.status,
                    )
    except Exception as exc:
        store.update_enrichment_checkpoint(
            CHECKPOINT_NAME,
            endpoint=endpoint,
            cursor=str(last_id),
            request_count=previous_request_count + run_request_count,
            status="error",
            error=str(exc),
        )
        raise

    result.inspected = inspected
    result.enriched = enriched
    result.request_count = run_request_count
    result.total_request_count = previous_request_count + run_request_count
    result.cursor = last_id
    log(
        f"[DONE] inspected={result.inspected} enriched={result.enriched} "
        f"run_request_count={result.request_count} "
        f"total_request_count={result.total_request_count} cursor={result.cursor}"
    )
    return result


def support_conditions_endpoint(public_service_api_url: str) -> str:
    return public_service_api_url.replace("/serviceList", "/supportConditions")


def fetch_support_conditions(
    client: httpx.Client,
    *,
    endpoint: str,
    service_key: str,
    service_id: str,
) -> dict[str, Any]:
    response = client.get(
        endpoint,
        params={
            "serviceKey": service_key,
            "page": 1,
            "perPage": 1,
            "returnType": "JSON",
            "cond[서비스ID::EQ]": service_id,
        },
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {400, 404}:
            return {}
        raise
    payload = parse_response_payload(response)
    items = extract_items(payload)
    return items[0] if items else {}

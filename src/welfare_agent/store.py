from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

import sqlite_vec

from welfare_agent.domain.schedule import (
    classify_period,
    evaluate_period,
    is_definitely_closed,
    today_kst,
)


BENEFIT_COLUMNS = (
    "id",
    "source",
    "external_id",
    "title",
    "summary",
    "target",
    "criteria",
    "content",
    "application_period",
    "business_period",
    "application_method",
    "organization",
    "contact",
    "url",
    "application_url",
    "extra_urls",
    "region_sido",
    "region_sigungu",
    "age_min",
    "age_max",
    "category",
    "raw_json",
    "search_text",
    "content_hash",
    "active",
    "last_seen_at",
    "updated_at",
)

# 사용자/매칭에 노출하는 정규화 필드(raw_json 제외).
_OUTPUT_FIELDS = (
    "id",
    "source",
    "external_id",
    "title",
    "summary",
    "target",
    "criteria",
    "content",
    "application_period",
    "business_period",
    "application_method",
    "organization",
    "contact",
    "url",
    "application_url",
    "extra_urls",
    "region_sido",
    "region_sigungu",
    "age_min",
    "age_max",
    "category",
)

CONDITION_FLAG_CODES = {
    "pregnant": ("JA0302", "JA0303"),
    "job_seeker": ("JA0327",),
    "disabled": ("JA0328",),
    "single_parent": ("JA0403",),
    "one_person_household": ("JA0404",),
    "no_home": ("JA0412",),
    "student": ("JA0317", "JA0318", "JA0319", "JA0320"),
}


class BenefitStore:
    def __init__(self, path: str, vector_dimensions: int = 1536):
        self.path = Path(path)
        self.vector_dimensions = vector_dimensions
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        load_vec_extension(db)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def init_schema(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS benefits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    target TEXT NOT NULL DEFAULT '',
                    criteria TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    application_period TEXT NOT NULL DEFAULT '',
                    business_period TEXT NOT NULL DEFAULT '',
                    application_method TEXT NOT NULL DEFAULT '',
                    organization TEXT NOT NULL DEFAULT '',
                    contact TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    application_url TEXT NOT NULL DEFAULT '',
                    extra_urls TEXT NOT NULL DEFAULT '',
                    region_sido TEXT NOT NULL DEFAULT '',
                    region_sigungu TEXT NOT NULL DEFAULT '',
                    age_min TEXT NOT NULL DEFAULT '',
                    age_max TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    search_text TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    last_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, external_id)
                )
                """
            )
            self._validate_benefits_schema(db)
            db.execute("CREATE INDEX IF NOT EXISTS idx_benefits_active ON benefits(active)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_benefits_source ON benefits(source)")
            db.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS benefit_embeddings
                USING vec0(embedding float[{self.vector_dimensions}])
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_locks (
                    name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    acquired_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS benefit_enrichments (
                    benefit_id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    support_conditions_json TEXT NOT NULL DEFAULT '{}',
                    support_conditions_hash TEXT NOT NULL DEFAULT '',
                    enriched_at TEXT NOT NULL,
                    FOREIGN KEY(benefit_id) REFERENCES benefits(id) ON DELETE CASCADE
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS benefit_condition_flags (
                    benefit_id INTEGER PRIMARY KEY,
                    age_min INTEGER,
                    age_max INTEGER,
                    pregnant INTEGER NOT NULL DEFAULT 0,
                    job_seeker INTEGER NOT NULL DEFAULT 0,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    single_parent INTEGER NOT NULL DEFAULT 0,
                    one_person_household INTEGER NOT NULL DEFAULT 0,
                    no_home INTEGER NOT NULL DEFAULT 0,
                    student INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(benefit_id) REFERENCES benefits(id) ON DELETE CASCADE
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS enrichment_checkpoints (
                    name TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    cursor TEXT NOT NULL DEFAULT '',
                    request_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'idle',
                    error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_benefit_enrichments_source "
                "ON benefit_enrichments(source)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_benefit_condition_flags_age "
                "ON benefit_condition_flags(age_min, age_max)"
            )

    def _validate_benefits_schema(self, db: sqlite3.Connection) -> None:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(benefits)").fetchall()}
        missing_columns = [column for column in BENEFIT_COLUMNS if column not in columns]
        if missing_columns:
            missing = ", ".join(missing_columns)
            raise RuntimeError(
                "Existing benefits DB schema is outdated. "
                f"Missing columns: {missing}. "
                "Back up or delete the DB, then run scripts/sync_benefits.py --mode full."
            )

    def upsert_benefit(
        self,
        benefit: dict[str, Any],
        *,
        source: str,
        embedding: list[float] | None = None,
    ) -> int:
        now = utc_now()
        external_id = benefit_external_id(benefit)
        raw = benefit.get("raw") or {}
        search_text = benefit_search_text(benefit)
        content_hash = benefit_content_hash(benefit, source=source)
        values = {column: "" for column in BENEFIT_COLUMNS}
        values.update(
            {
                "source": source,
                "external_id": external_id,
                "title": benefit.get("title", ""),
                "summary": benefit.get("summary", ""),
                "target": benefit.get("target", ""),
                "criteria": benefit.get("criteria", ""),
                "content": benefit.get("content", ""),
                "application_period": benefit.get("application_period", ""),
                "business_period": benefit.get("business_period", ""),
                "application_method": benefit.get("application_method", ""),
                "organization": benefit.get("organization", ""),
                "contact": benefit.get("contact", ""),
                "url": benefit.get("url", ""),
                "application_url": benefit.get("application_url", ""),
                "extra_urls": benefit.get("extra_urls", ""),
                "region_sido": benefit.get("region_sido", ""),
                "region_sigungu": benefit.get("region_sigungu", ""),
                "age_min": str(benefit.get("age_min", "") or ""),
                "age_max": str(benefit.get("age_max", "") or ""),
                "category": benefit.get("category", ""),
                "raw_json": json.dumps(raw, ensure_ascii=False, sort_keys=True),
                "search_text": search_text,
                "content_hash": content_hash,
                "active": 1,
                "last_seen_at": now,
                "updated_at": now,
            }
        )
        insert_columns = [column for column in BENEFIT_COLUMNS if column != "id"]
        placeholders = ", ".join(f":{column}" for column in insert_columns)
        update_clause = ", ".join(
            f"{column} = excluded.{column}"
            for column in insert_columns
            if column not in ("source", "external_id")
        )
        with self.connect() as db:
            db.execute(
                f"""
                INSERT INTO benefits ({", ".join(insert_columns)})
                VALUES ({placeholders})
                ON CONFLICT(source, external_id) DO UPDATE SET {update_clause}
                """,
                values,
            )
            row = db.execute(
                "SELECT id FROM benefits WHERE source = ? AND external_id = ?",
                (source, external_id),
            ).fetchone()
            benefit_id = int(row["id"])
            if embedding:
                self._replace_embedding(db, benefit_id, embedding)
            return benefit_id

    def search(
        self,
        *,
        embedding: list[float],
        limit: int = 10,
        available_on: str | None = None,
        include_unknown_periods: bool = True,
    ) -> list[dict[str, Any]]:
        try:
            with self.connect() as db:
                _ = include_unknown_periods  # Kept for MCP compatibility; unknown periods are fail-open.
                match_limit = max(limit * 10, 50) if available_on else limit
                rows = db.execute(
                    """
                    WITH matches AS (
                        SELECT rowid, distance
                        FROM benefit_embeddings
                        WHERE embedding MATCH ?
                        ORDER BY distance
                        LIMIT ?
                    )
                    SELECT
                        b.*,
                        matches.distance,
                        cf.age_min AS condition_age_min,
                        cf.age_max AS condition_age_max,
                        cf.pregnant AS condition_pregnant,
                        cf.job_seeker AS condition_job_seeker,
                        cf.disabled AS condition_disabled,
                        cf.single_parent AS condition_single_parent,
                        cf.one_person_household AS condition_one_person_household,
                        cf.no_home AS condition_no_home,
                        cf.student AS condition_student
                    FROM matches
                    JOIN benefits b ON b.id = matches.rowid
                    LEFT JOIN benefit_condition_flags cf ON cf.benefit_id = b.id
                    WHERE b.active = 1
                    ORDER BY matches.distance
                    LIMIT ?
                    """,
                    (json.dumps(embedding), match_limit, match_limit),
                ).fetchall()
                items = [row_to_benefit(row) for row in rows]
                if available_on:
                    items = [
                        item for item in items
                        if not is_definitely_closed(item, today=available_on)
                    ]
                return items[:limit]
        except sqlite3.Error:
            return []

    def count_active(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) AS count FROM benefits WHERE active = 1").fetchone()
            return int(row["count"])

    def count_source(self, source: str) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS count FROM benefits WHERE source = ?",
                (source,),
            ).fetchone()
            return int(row["count"])

    def get_benefit_state(self, source: str, external_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT content_hash, active FROM benefits WHERE source = ? AND external_id = ?",
                (source, external_id),
            ).fetchone()
            if not row:
                return None
            return {"content_hash": row["content_hash"], "active": bool(row["active"])}

    def mark_source_inactive_if_stale(self, source: str, seen_at: str) -> int:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE benefits SET active = 0 WHERE source = ? AND last_seen_at < ?",
                (source, seen_at),
            )
            return cursor.rowcount

    def list_public_service_ids_for_enrichment(
        self,
        *,
        after_id: int = 0,
        limit: int = 100,
        missing_only: bool = True,
    ) -> list[dict[str, Any]]:
        with self.connect() as db:
            join_clause = (
                "LEFT JOIN benefit_enrichments e ON e.benefit_id = b.id "
                if missing_only else ""
            )
            missing_clause = "AND e.benefit_id IS NULL" if missing_only else ""
            rows = db.execute(
                f"""
                SELECT b.id, b.external_id, b.title
                FROM benefits b
                {join_clause}
                WHERE b.active = 1
                  AND b.source = 'public_service_benefits'
                  AND b.id > ?
                  {missing_clause}
                ORDER BY b.id
                LIMIT ?
                """,
                (after_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_support_conditions(self, benefit_id: int, support_conditions: dict[str, Any]) -> None:
        from welfare_agent.ingestion.normalize import normalize_item

        now = utc_now()
        normalized = normalize_item(support_conditions, "public_service_benefits")
        condition_flags = condition_flags_from_support_conditions(support_conditions)
        with self.connect() as db:
            row = db.execute("SELECT * FROM benefits WHERE id = ?", (benefit_id,)).fetchone()
            if not row:
                return
            item = row_to_benefit(row)
            raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
            raw["supportConditions"] = support_conditions
            item.update(
                {
                    "age_min": normalized.get("age_min") or item.get("age_min", ""),
                    "age_max": normalized.get("age_max") or item.get("age_max", ""),
                    "raw": raw,
                }
            )
            search_text = benefit_search_text(item)
            raw_json = json.dumps(raw, ensure_ascii=False, sort_keys=True)
            payload_hash = stable_hash(support_conditions)
            db.execute(
                """
                INSERT INTO benefit_enrichments (
                    benefit_id, source, external_id, support_conditions_json,
                    support_conditions_hash, enriched_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(benefit_id) DO UPDATE SET
                    support_conditions_json = excluded.support_conditions_json,
                    support_conditions_hash = excluded.support_conditions_hash,
                    enriched_at = excluded.enriched_at
                """,
                (
                    benefit_id,
                    row["source"],
                    row["external_id"],
                    json.dumps(support_conditions, ensure_ascii=False, sort_keys=True),
                    payload_hash,
                    now,
                ),
            )
            db.execute(
                """
                INSERT INTO benefit_condition_flags (
                    benefit_id, age_min, age_max, pregnant, job_seeker, disabled,
                    single_parent, one_person_household, no_home, student, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(benefit_id) DO UPDATE SET
                    age_min = excluded.age_min,
                    age_max = excluded.age_max,
                    pregnant = excluded.pregnant,
                    job_seeker = excluded.job_seeker,
                    disabled = excluded.disabled,
                    single_parent = excluded.single_parent,
                    one_person_household = excluded.one_person_household,
                    no_home = excluded.no_home,
                    student = excluded.student,
                    updated_at = excluded.updated_at
                """,
                (
                    benefit_id,
                    _optional_int(item.get("age_min", "")),
                    _optional_int(item.get("age_max", "")),
                    int(condition_flags["pregnant"]),
                    int(condition_flags["job_seeker"]),
                    int(condition_flags["disabled"]),
                    int(condition_flags["single_parent"]),
                    int(condition_flags["one_person_household"]),
                    int(condition_flags["no_home"]),
                    int(condition_flags["student"]),
                    now,
                ),
            )
            db.execute(
                """
                UPDATE benefits
                SET age_min = ?,
                    age_max = ?,
                    raw_json = ?,
                    search_text = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    item.get("age_min", ""),
                    item.get("age_max", ""),
                    raw_json,
                    search_text,
                    now,
                    benefit_id,
                ),
            )

    def get_enrichment_checkpoint(self, name: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM enrichment_checkpoints WHERE name = ?",
                (name,),
            ).fetchone()
            return dict(row) if row else None

    def update_enrichment_checkpoint(
        self,
        name: str,
        *,
        endpoint: str,
        cursor: str,
        request_count: int,
        status: str,
        error: str = "",
    ) -> None:
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO enrichment_checkpoints (
                    name, endpoint, cursor, request_count, status, error, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    endpoint = excluded.endpoint,
                    cursor = excluded.cursor,
                    request_count = excluded.request_count,
                    status = excluded.status,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (name, endpoint, cursor, request_count, status, error, now),
            )

    def acquire_sync_lock(self, name: str, *, owner: str, ttl_seconds: int) -> bool:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT owner, expires_at FROM sync_locks WHERE name = ?",
                (name,),
            ).fetchone()
            if row and row["expires_at"] > now.isoformat():
                return False
            db.execute(
                """
                INSERT INTO sync_locks (name, owner, expires_at, acquired_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    owner = excluded.owner,
                    expires_at = excluded.expires_at,
                    acquired_at = excluded.acquired_at
                """,
                (name, owner, expires_at.isoformat(), now.isoformat()),
            )
            return True

    def release_sync_lock(self, name: str, *, owner: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM sync_locks WHERE name = ? AND owner = ?", (name, owner))

    def _replace_embedding(
        self, db: sqlite3.Connection, benefit_id: int, embedding: list[float]
    ) -> None:
        db.execute("DELETE FROM benefit_embeddings WHERE rowid = ?", (benefit_id,))
        db.execute(
            "INSERT INTO benefit_embeddings(rowid, embedding) VALUES (?, ?)",
            (benefit_id, json.dumps(embedding)),
        )


def load_vec_extension(db: sqlite3.Connection) -> None:
    db.enable_load_extension(True)
    try:
        sqlite_vec.load(db)
    finally:
        db.enable_load_extension(False)


def row_to_benefit(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    raw_json = row["raw_json"] if "raw_json" in keys else "{}"
    try:
        raw = json.loads(raw_json)
    except json.JSONDecodeError:
        raw = {}
    item = {field: (row[field] if field in keys else "") for field in _OUTPUT_FIELDS}
    item["raw"] = raw
    period = evaluate_period(item, today=today_kst())
    item.update(period)
    item["application_status"] = period["period_status"]
    if "distance" in keys:
        item["vector_distance"] = row["distance"]
    condition_prefix = "condition_"
    condition_flags = {
        name: bool(row[f"{condition_prefix}{name}"])
        for name in CONDITION_FLAG_CODES
        if f"{condition_prefix}{name}" in keys and row[f"{condition_prefix}{name}"] is not None
    }
    if "condition_age_min" in keys and row["condition_age_min"] is not None:
        condition_flags["age_min"] = int(row["condition_age_min"])
    if "condition_age_max" in keys and row["condition_age_max"] is not None:
        condition_flags["age_max"] = int(row["condition_age_max"])
    if condition_flags:
        item["condition_flags"] = condition_flags
    return item


def benefit_external_id(benefit: dict[str, Any]) -> str:
    for key in ("id", "url", "title"):
        value = benefit.get(key)
        if value:
            return str(value)
    return stable_hash(benefit.get("raw") or benefit)


def benefit_content_hash(benefit: dict[str, Any], *, source: str) -> str:
    # 원본(raw) 기준으로만 해싱한다. 상세 보강은 raw로부터 결정적으로 도출되므로
    # 보강 전/후 해시가 동일해 증분 동기화가 안정적으로 유지된다.
    external_id = benefit_external_id(benefit)
    raw = benefit.get("raw") or {}
    return stable_hash({"source": source, "external_id": external_id, "raw": raw})


def benefit_search_text(benefit: dict[str, Any]) -> str:
    raw = benefit.get("raw") or {}
    parts = [
        benefit.get("title", ""),
        benefit.get("summary", ""),
        benefit.get("target", ""),
        benefit.get("criteria", ""),
        benefit.get("content", ""),
        benefit.get("business_period", ""),
        benefit.get("category", ""),
        benefit.get("region_sido", ""),
        benefit.get("region_sigungu", ""),
        benefit.get("application_period", ""),
        benefit.get("application_method", ""),
        benefit.get("organization", ""),
    ]
    for key in ("서비스분야", "사용자구분", "lclsfNm", "mclsfNm", "plcyKywdNm", "hashtags"):
        if raw.get(key):
            parts.append(str(raw[key]))
    return "\n".join(part for part in parts if part).strip()


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def condition_flags_from_support_conditions(conditions: dict[str, Any]) -> dict[str, bool]:
    return {
        flag: any(_truthy_condition_flag(conditions.get(code)) for code in codes)
        for flag, codes in CONDITION_FLAG_CODES.items()
    }


def _truthy_condition_flag(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text and text not in {"n", "no", "false", "0", "해당없음", "없음", "-"})


def _optional_int(value: Any) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


# 하위 호환: 기존 호출부/테스트가 기대하는 이름.
def parse_application_window(period: str) -> dict[str, Any]:
    return classify_period(period)

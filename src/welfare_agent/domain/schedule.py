from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any
from zoneinfo import ZoneInfo


# 신청 기간 분류 유형.
SCHEDULE_DATED = "dated"  # 명확한 신청 시작/마감 날짜가 있음
SCHEDULE_ALWAYS = "always"  # 상시/연중/수시 신청
SCHEDULE_NO_APPLICATION = "no_application"  # 별도 신청 절차가 없음(자동 지원 등)
SCHEDULE_UNTIL_FUNDS = "until_funds"  # 예산 소진/선착순 등 마감일 미정·조기마감 가능
SCHEDULE_PERIODIC = "periodic"  # 매년/매월/연초 등 반복(해당 연도 날짜 불명확)
SCHEDULE_CHECK = "check_required"  # 접수기관별 상이/추후 공지 등 공고 확인 필요
SCHEDULE_UNKNOWN = "unknown"  # 신청 기간 정보 없음

PERIOD_STATUS_OPEN = "open"
PERIOD_STATUS_UPCOMING = "upcoming"
PERIOD_STATUS_CLOSED = "closed"
PERIOD_STATUS_NO_APPLICATION = "no_application"
PERIOD_STATUS_NEEDS_CHECK = "needs_check"

PERIOD_PARSE_PARSED = "parsed"
PERIOD_PARSE_CODE = "code"
PERIOD_PARSE_EMPTY = "empty"
PERIOD_PARSE_AMBIGUOUS = "ambiguous"
PERIOD_PARSE_UNPARSED = "unparsed"

# 마감일이 없는(=언제든 신청 가능) 것으로 간주하는 분류.
OPEN_ENDED_TYPES = frozenset({SCHEDULE_ALWAYS, SCHEDULE_NO_APPLICATION, SCHEDULE_UNTIL_FUNDS})

_ALWAYS_KEYWORDS = ("상시", "연중", "수시")
_NO_APPLICATION_KEYWORDS = (
    "신청불필요",
    "신청 불필요",
    "신청불요",
    "신청 불요",
    "별도의 신청절차",
    "별도 신청절차",
    "별도의 신청 절차",
    "신청절차가 없",
    "신청 절차가 없",
    "개인 신청절차 없",
    "개인신청절차 없",
    "별도의 신청 없",
)
_UNTIL_FUNDS_KEYWORDS = (
    "예산 소진",
    "예산소진",
    "소진시",
    "소진 시",
    "선착순",
    "모집 완료시",
    "모집완료시",
    "모집 마감시",
)
_PERIODIC_KEYWORDS = (
    "매년",
    "매월",
    "매분기",
    "매 분기",
    "분기별",
    "연초",
    "연말",
    "상반기",
    "하반기",
)
_CHECK_KEYWORDS = (
    "접수기관",
    "별도 공고",
    "별도공고",
    "공고 확인",
    "공고확인",
    "공고에 따름",
    "공고문 확인",
    "추후 공지",
    "추후공지",
    "시군구청에 따라",
    "주민센터에 따라",
    "세부사업별",
    "세부 사업별",
    "별도 안내",
    "별도안내",
    "별도 문의",
    "기관 문의",
    "기관문의",
)

_HUMAN_LABEL = {
    SCHEDULE_DATED: "신청 기간 있음",
    SCHEDULE_ALWAYS: "상시 신청",
    SCHEDULE_NO_APPLICATION: "별도 신청 불필요",
    SCHEDULE_UNTIL_FUNDS: "예산 소진 시까지(조기 마감 가능)",
    SCHEDULE_PERIODIC: "매년/정기 모집(해당 연도 공고 확인 필요)",
    SCHEDULE_CHECK: "접수기관/공고 확인 필요",
    SCHEDULE_UNKNOWN: "신청 기간 미확인",
}


# 신청기간 문자열을 분류 유형 + 시작/종료 날짜로 구조화한다.
def classify_period(period: str) -> dict[str, Any]:
    text = (period or "").strip()
    dates = extract_dates(text)
    schedule_type = _keyword_type(text)

    start_date = ""
    end_date = ""
    if len(dates) >= 2:
        start_date = dates[0].isoformat()
        end_date = dates[-1].isoformat()
        if schedule_type in (None, SCHEDULE_PERIODIC, SCHEDULE_CHECK):
            schedule_type = SCHEDULE_DATED
    elif len(dates) == 1:
        # 단일 날짜는 마감일로 간주한다(시작일은 알 수 없음).
        end_date = dates[0].isoformat()
        if schedule_type in (None, SCHEDULE_PERIODIC, SCHEDULE_CHECK):
            schedule_type = SCHEDULE_DATED

    if schedule_type is None:
        schedule_type = SCHEDULE_UNKNOWN if not text else SCHEDULE_CHECK

    return {
        "schedule_type": schedule_type,
        "start_date": start_date,
        "end_date": end_date,
        "always_open": schedule_type in OPEN_ENDED_TYPES,
    }


def _keyword_type(text: str) -> str | None:
    if not text:
        return None
    if any(keyword in text for keyword in _NO_APPLICATION_KEYWORDS):
        return SCHEDULE_NO_APPLICATION
    if any(keyword in text for keyword in _UNTIL_FUNDS_KEYWORDS):
        return SCHEDULE_UNTIL_FUNDS
    if any(keyword in text for keyword in _ALWAYS_KEYWORDS):
        return SCHEDULE_ALWAYS
    if any(keyword in text for keyword in _PERIODIC_KEYWORDS):
        return SCHEDULE_PERIODIC
    if any(keyword in text for keyword in _CHECK_KEYWORDS):
        return SCHEDULE_CHECK
    return None


# 신청기간 문자열에서 날짜를 추출한다(YYYYMMDD / YYYY-MM-DD / YYYY.M.D / YYYY년 M월 D일).
def extract_dates(text: str) -> list[date]:
    dates: list[date] = []
    for match in re.finditer(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", text):
        _append_date(dates, match.group(1), match.group(2), match.group(3))
    for match in re.finditer(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})", text):
        _append_date(dates, match.group(1), match.group(2), match.group(3))
    return sorted(set(dates))


def _append_date(dates: list[date], year: str, month: str, day: str) -> None:
    try:
        dates.append(date(int(year), int(month), int(day)))
    except ValueError:
        return


# 신청기간 분류를 사람이 읽을 수 있는 한 줄 설명으로 바꾼다.
def schedule_label(schedule_type: str) -> str:
    return _HUMAN_LABEL.get(schedule_type, _HUMAN_LABEL[SCHEDULE_UNKNOWN])


def evaluate_period(item: dict[str, Any], *, today: str) -> dict[str, Any]:
    """Return conservative period metadata from official source fields only.

    This is intentionally fail-open: unclear or unparsed periods are marked
    needs_check instead of being treated as closed.
    """
    source = str(item.get("source", "") or "")
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    basis = _period_basis(source, raw, str(item.get("application_period", "") or ""))
    text = basis["text"].strip()
    source_label = basis["source"]
    source_kind = basis["kind"]

    if source_kind == "official_code":
        status = _status_from_official_code(source, text)
        if status:
            return _period_result(
                status=status,
                parse_status=PERIOD_PARSE_CODE,
                source=source_label,
                reason=_reason_for_code_status(status),
                can_exclude=status == PERIOD_STATUS_CLOSED,
            )

    if source_kind == "official_structured_dates":
        start = _compact_date(_pick_raw(raw, "beginDe"))
        end = _compact_date(_pick_raw(raw, "endDe"))
        return _status_from_dates(
            start=start,
            end=end,
            today=today,
            source=source_label,
            reason_prefix="공식 신청 시작/종료일 필드 기준",
        )

    if not text:
        return _period_result(
            status=PERIOD_STATUS_NEEDS_CHECK,
            parse_status=PERIOD_PARSE_EMPTY,
            source=source_label,
            reason="공식 신청기간 필드가 비어 있어 마감 여부를 확정하지 않았습니다.",
        )

    if source_kind != "official_text":
        return _period_result(
            status=PERIOD_STATUS_NEEDS_CHECK,
            parse_status=PERIOD_PARSE_UNPARSED,
            source=source_label,
            reason="공식 신청기간 출처가 확인되지 않아 후보에서 제외하지 않았습니다.",
        )

    keyword_status = _status_from_text_keywords(text)
    if keyword_status:
        status, parse_status, reason, can_exclude = keyword_status
        return _period_result(
            status=status,
            parse_status=parse_status,
            source=source_label,
            reason=reason,
            can_exclude=can_exclude,
        )

    dates = extract_dates(text)
    if len(dates) >= 2:
        return _status_from_dates(
            start=dates[0].isoformat(),
            end=dates[-1].isoformat(),
            today=today,
            source=source_label,
            reason_prefix="공식 신청기간 문구의 시작/종료일 기준",
        )
    if len(dates) == 1 and _source_is_deadline(source_label):
        return _status_from_dates(
            start="",
            end=dates[0].isoformat(),
            today=today,
            source=source_label,
            reason_prefix="공식 신청기한 필드의 마감일 기준",
        )

    return _period_result(
        status=PERIOD_STATUS_NEEDS_CHECK,
        parse_status=PERIOD_PARSE_AMBIGUOUS,
        source=source_label,
        reason="공식 신청기간을 확정 날짜 범위로 해석할 수 없어 후보에서 제외하지 않았습니다.",
    )


def is_definitely_closed(item: dict[str, Any], *, today: str) -> bool:
    period = evaluate_period(item, today=today)
    return period["period_status"] == PERIOD_STATUS_CLOSED and bool(period["period_can_exclude"])


def _period_basis(source: str, raw: dict[str, Any], fallback_text: str) -> dict[str, str]:
    if source == "youth_policy":
        aply_ymd = _pick_raw(raw, "aplyYmd")
        if aply_ymd:
            return {"text": aply_ymd, "source": "api_field:aplyYmd", "kind": "official_text"}
        code = _pick_raw(raw, "aplyPrdSeCd")
        if code:
            return {"text": code, "source": "api_code:aplyPrdSeCd", "kind": "official_code"}
    if source == "public_service_benefits":
        deadline = _pick_raw(raw, "신청기한")
        if deadline:
            return {"text": deadline, "source": "api_field:신청기한", "kind": "official_text"}

    for field in ("applicationPeriod", "aplyPrd", "신청기간", "신청기한", "reqstBeginEndDe"):
        value = _pick_raw(raw, field)
        if value:
            return {"text": value, "source": f"api_field:{field}", "kind": "official_text"}
    return {"text": fallback_text, "source": "unknown", "kind": "unknown"}


def _status_from_official_code(source: str, code: str) -> str:
    if source == "youth_policy":
        if code == "0057002":
            return PERIOD_STATUS_OPEN
        if code == "0057003":
            return PERIOD_STATUS_CLOSED
    return ""


def _reason_for_code_status(status: str) -> str:
    if status == PERIOD_STATUS_CLOSED:
        return "공식 신청기간구분코드가 마감 상태입니다."
    if status == PERIOD_STATUS_OPEN:
        return "공식 신청기간구분코드가 상시 신청 상태입니다."
    return "공식 신청기간구분코드 기준입니다."


def _status_from_text_keywords(text: str) -> tuple[str, str, str, bool] | None:
    stripped = re.sub(r"\s+", "", text)
    if stripped in ("마감", "접수마감", "신청마감"):
        return (
            PERIOD_STATUS_CLOSED,
            PERIOD_PARSE_CODE,
            "공식 신청기간 문구가 마감 상태입니다.",
            True,
        )
    if any(keyword in text for keyword in _NO_APPLICATION_KEYWORDS):
        return (
            PERIOD_STATUS_NO_APPLICATION,
            PERIOD_PARSE_CODE,
            "공식 신청기간 문구가 별도 신청 불필요로 제공되었습니다.",
            False,
        )
    if any(keyword in text for keyword in _ALWAYS_KEYWORDS):
        return (
            PERIOD_STATUS_OPEN,
            PERIOD_PARSE_CODE,
            "공식 신청기간 문구가 상시/연중 신청으로 제공되었습니다.",
            False,
        )
    if any(keyword in text for keyword in _UNTIL_FUNDS_KEYWORDS):
        return (
            PERIOD_STATUS_OPEN,
            PERIOD_PARSE_AMBIGUOUS,
            "예산 소진/선착순 문구라 조기 마감 가능성이 있어 공고 확인이 필요합니다.",
            False,
        )
    if any(keyword in text for keyword in _CHECK_KEYWORDS) or any(keyword in text for keyword in _PERIODIC_KEYWORDS):
        return (
            PERIOD_STATUS_NEEDS_CHECK,
            PERIOD_PARSE_AMBIGUOUS,
            "공식 신청기간 문구가 기관별/정기/공고 확인 필요 상태입니다.",
            False,
        )
    return None


def _status_from_dates(
    *,
    start: str,
    end: str,
    today: str,
    source: str,
    reason_prefix: str,
) -> dict[str, Any]:
    if start and today < start:
        status = PERIOD_STATUS_UPCOMING
        reason = f"{reason_prefix}: 신청 시작일이 기준일 이후입니다."
    elif end and today > end:
        status = PERIOD_STATUS_CLOSED
        reason = f"{reason_prefix}: 신청 종료일이 기준일 이전입니다."
    elif start or end:
        status = PERIOD_STATUS_OPEN
        reason = f"{reason_prefix}: 기준일에 신청 가능 범위로 판단됩니다."
    else:
        return _period_result(
            status=PERIOD_STATUS_NEEDS_CHECK,
            parse_status=PERIOD_PARSE_EMPTY,
            source=source,
            reason="공식 신청 시작/종료일 필드가 비어 있어 마감 여부를 확정하지 않았습니다.",
        )
    return _period_result(
        status=status,
        parse_status=PERIOD_PARSE_PARSED,
        source=source,
        start_date=start,
        end_date=end,
        reason=reason,
        can_exclude=status == PERIOD_STATUS_CLOSED,
    )


def _period_result(
    *,
    status: str,
    parse_status: str,
    source: str,
    reason: str,
    start_date: str = "",
    end_date: str = "",
    can_exclude: bool = False,
) -> dict[str, Any]:
    return {
        "period_status": status,
        "period_parse_status": parse_status,
        "period_source": source,
        "period_start_date": start_date,
        "period_end_date": end_date,
        "period_can_exclude": can_exclude,
        "period_reason": reason,
    }


def _pick_raw(raw: dict[str, Any], *names: str) -> str:
    lower = {str(key).lower(): value for key, value in raw.items()}
    for name in names:
        value = raw.get(name)
        if value in (None, ""):
            value = lower.get(name.lower())
        if value not in (None, "", [], {}):
            return str(value).strip()
    return ""


def _compact_date(value: str) -> str:
    match = re.match(r"^(20\d{2})\D?(\d{2})\D?(\d{2})", value or "")
    if not match:
        return ""
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return ""


def _source_is_deadline(source: str) -> bool:
    return "기한" in source or "deadline" in source.lower()


def today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None

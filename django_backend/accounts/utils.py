"""Shared helpers: date/time-zone handling, filtering and a minimal PDF writer."""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.utils import timezone


def _attendance_tz():
    """The configured attendance time zone, falling back to UTC if unknown."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(settings.ATTENDANCE_TIME_ZONE)
    except Exception:
        return dt.timezone.utc


def local_date(timestamp=None) -> dt.date:
    """The attendance 'business date' for a moment in time, in ATTENDANCE_TIME_ZONE."""
    moment = timestamp or timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, dt.timezone.utc)
    return moment.astimezone(_attendance_tz()).date()


def local_date_string(timestamp=None) -> str:
    return local_date(timestamp).isoformat()


def valid_date_string(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return dt.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def parse_iso_datetime(value):
    """Parse an ISO-8601 string (e.g. from JS ``toISOString()``) into an aware datetime."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt.timezone.utc)
    return parsed


def filtered_records(queryset, *, from_date="", to_date="", employee_uuid="", month=""):
    """Apply the admin dashboard's date/employee filters to an attendance queryset."""
    if from_date:
        if not valid_date_string(from_date):
            raise ValueError("Use valid date filters in YYYY-MM-DD format.")
        queryset = queryset.filter(date__gte=from_date)
    if to_date:
        if not valid_date_string(to_date):
            raise ValueError("Use valid date filters in YYYY-MM-DD format.")
        queryset = queryset.filter(date__lte=to_date)
    if employee_uuid:
        queryset = queryset.filter(employee__uuid=employee_uuid)
    if month:
        if len(month) != 7 or month[4] != "-":
            raise ValueError("Use a valid month filter in YYYY-MM format.")
        queryset = queryset.filter(date__startswith=month)
    return list(queryset.order_by("-date"))


def make_pdf(lines) -> bytes:
    """
    Produce a small, valid PDF from plain-text lines.

    This mirrors the previous Node implementation (Helvetica, 45 lines/page) so
    downloaded reports stay byte-similar in layout without adding a dependency.
    """

    def escape(line: str) -> str:
        text = "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in str(line))
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    safe_lines = [escape(line) for line in lines]
    pages = [safe_lines[i : i + 45] for i in range(0, len(safe_lines), 45)] or [[]]

    objects: dict[int, str] = {}
    page_ids = [4 + index * 2 for index in range(len(pages))]
    objects[1] = "<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>"
    objects[3] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for index, page in enumerate(pages):
        page_id = page_ids[index]
        stream_id = page_id + 1
        content = (
            "BT /F1 9 Tf 42 800 Td 13 TL "
            + " ".join(f"({line}) Tj T*" for line in page)
            + " ET"
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>"
        )
        objects[stream_id] = (
            f"<< /Length {len(content.encode('ascii'))} >>\nstream\n{content}\nendstream"
        )

    total = max(objects) + 1
    output = "%PDF-1.4\n"
    offsets = [0] * total
    for i in range(1, total):
        offsets[i] = len(output.encode("ascii"))
        output += f"{i} 0 obj\n{objects[i]}\nendobj\n"
    xref_offset = len(output.encode("ascii"))
    output += f"xref\n0 {total}\n0000000000 65535 f \n"
    for i in range(1, total):
        output += f"{offsets[i]:010d} 00000 n \n"
    output += f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    return output.encode("ascii")

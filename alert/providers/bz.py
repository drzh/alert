"""Interplanetary magnetic field Bz provider."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable, Sequence

from alert.models import AlertItem, StoredAlert, TargetConfig
from alert.providers.base import AlertProvider

TRIM_SECONDS_PATTERN = re.compile(r":\d{2}(?:\.\d+)?$")


class BzProvider(AlertProvider):
    name = "bz"
    default_email_title = "Bz Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        threshold = target.threshold if target.threshold is not None else -10.0
        rows = list(_iter_rows(content))
        if not rows:
            return []

        parsed_rows = []
        for row in rows:
            time_tag = _string_value(row.get("time_tag"))
            bz_value = _to_float(row.get("bz_gsm"))
            if time_tag is None or bz_value is None:
                continue
            parsed_rows.append((time_tag, bz_value))

        if not parsed_rows:
            return []

        time_tag_now, _ = parsed_rows[-1]
        time_tag_min, bz_min = min(parsed_rows, key=lambda pair: pair[1])
        if bz_min >= threshold:
            return []

        message = (
            f"Bz = {bz_min} nT  :  {_trim_time_tag(time_tag_min)} (UTC)  :  "
            f"current time {_trim_time_tag(time_tag_now)} (UTC)."
        )
        return [
            AlertItem(
                item_id=time_tag_min,
                message=message,
                value=str(bz_min),
                occurred_at=time_tag_min,
            )
        ]

    def should_alert(
        self,
        history: Sequence[StoredAlert],
        item: AlertItem,
        target: TargetConfig,
    ) -> bool:
        if not history:
            return True

        new_value = _to_float(item.value)
        new_time = _parse_time_tag(item.occurred_at or item.item_id)
        if new_value is None or new_time is None:
            return False

        min_record = None
        min_value = None
        for record in history:
            record_value = _to_float(record.value)
            if record_value is None:
                continue
            if min_value is None or record_value < min_value:
                min_value = record_value
                min_record = record

        if min_record is None or min_value is None or new_value >= min_value:
            return False

        previous_time = _parse_time_tag(min_record.occurred_at or min_record.item_id)
        if previous_time is None:
            return False

        return (new_time - previous_time).total_seconds() >= 60 * 60


def _iter_rows(content: str) -> Iterable[dict[str, object]]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, list) and payload:
        if all(isinstance(row, dict) for row in payload):
            return payload
        if all(isinstance(row, list) for row in payload):
            headers = [str(value) for value in payload[0]]
            return [
                {headers[index]: row[index] for index in range(min(len(headers), len(row)))}
                for row in payload[1:]
                if isinstance(row, list)
            ]

    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                nested_rows = _iter_rows(json.dumps(value))
                nested_rows = list(nested_rows)
                if nested_rows:
                    return nested_rows

    return []


def _string_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trim_time_tag(value: str) -> str:
    return TRIM_SECONDS_PATTERN.sub("", value)


def _parse_time_tag(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = value.strip().replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace(" ", "T")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


PROVIDER = BzProvider()

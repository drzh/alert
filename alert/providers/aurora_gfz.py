"""GFZ aurora forecast provider."""

from __future__ import annotations

import csv
import re
from io import StringIO
from typing import Sequence

from alert.models import AlertItem, StoredAlert, TargetConfig
from alert.providers.base import AlertProvider

TIME_PATTERN = re.compile(r"(\d{2})-(\d{2})-(\d{4}) (\d{2}:\d{2})")


class AuroraGfzProvider(AlertProvider):
    name = "aurora_gfz"
    default_email_title = "GFZ Aurora Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        threshold = target.threshold if target.threshold is not None else 7.0
        reader = csv.DictReader(StringIO(content))
        items: list[AlertItem] = []
        for row in reader:
            kp_value = _to_float(row.get("median"))
            time_utc = row.get("Time (UTC)")
            if kp_value is None or time_utc is None or kp_value < threshold:
                continue
            occurred_at = _normalize_time(time_utc)
            message = f"median Kp = {kp_value} at {occurred_at} <br/><br/>"
            items.append(
                AlertItem(
                    item_id=occurred_at,
                    message=message,
                    value=str(kp_value),
                    occurred_at=occurred_at,
                )
            )
        return items

    def should_alert(
        self,
        history: Sequence[StoredAlert],
        item: AlertItem,
        target: TargetConfig,
    ) -> bool:
        new_value = _to_float(item.value)
        if new_value is None:
            return False

        max_previous = max(
            (_to_float(record.value) for record in history if record.value is not None),
            default=None,
        )
        return max_previous is None or new_value > max_previous


def _normalize_time(value: str) -> str:
    match = TIME_PATTERN.match(value.strip())
    if not match:
        return value.strip()
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)} {match.group(4)}"


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


PROVIDER = AuroraGfzProvider()

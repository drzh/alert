"""Heavens-Above comet and asteroid alert provider."""

from __future__ import annotations

from html import unescape
import re
from typing import Sequence

from alert.models import AlertItem, StoredAlert, TargetConfig
from alert.providers._helpers import html_link
from alert.providers.base import AlertProvider

ROW_PATTERN = re.compile(r'(<tr><td><a .*?>.*?</a></td>.*?</tr>)', re.DOTALL)
ENTRY_PATTERN = re.compile(
    r'<td><a .*?href="(.+?)".*?>(.+?)</a></td><td.*?>(.+?)</td>',
    re.DOTALL,
)


class HeavensAboveCometProvider(AlertProvider):
    name = "ha_comet"
    default_email_title = "Comet and Asteroids (Heavens Above) Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        threshold = target.threshold if target.threshold is not None else 6.0
        items: list[AlertItem] = []
        for block in ROW_PATTERN.findall(content):
            match = ENTRY_PATTERN.search(block)
            if match is None:
                continue

            relative_link, name, magnitude_text = (unescape(part.strip()) for part in match.groups())
            magnitude = _to_float(magnitude_text)
            if magnitude is None or magnitude > threshold:
                continue

            absolute_link = (
                relative_link
                if relative_link.startswith("http")
                else f"https://heavens-above.com/{relative_link.lstrip('/')}"
            )
            items.append(
                AlertItem(
                    item_id=f"{name}:{magnitude:g}",
                    message=f"{name} : {magnitude:g} : {html_link(absolute_link)}<br/><br/>",
                    value=f"{magnitude:g}",
                    metadata={"stable_id": name, "url": absolute_link},
                )
            )
        return items

    def should_alert(
        self,
        history: Sequence[StoredAlert],
        item: AlertItem,
        target: TargetConfig,
    ) -> bool:
        stable_id = str(item.metadata.get("stable_id", item.item_id))
        new_value = _to_float(item.value)
        if new_value is None:
            return False

        relevant_values = [
            value
            for record in history
            if record.metadata.get("stable_id", record.item_id) == stable_id
            for value in [_to_float(record.value)]
            if value is not None
        ]
        if not relevant_values:
            return True
        return new_value < min(relevant_values)


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


PROVIDER = HeavensAboveCometProvider()

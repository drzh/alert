"""spaceweather.com provider."""

from __future__ import annotations

import re

from alert.models import AlertItem, TargetConfig
from alert.providers.base import AlertProvider

ITEM_PATTERN = re.compile(r"<p [^>]*>(<strong>.+?)</p>", re.MULTILINE | re.DOTALL)


class SpaceweatherComProvider(AlertProvider):
    name = "spaceweather_com"
    default_email_title = "spaceweather.com Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        items: list[AlertItem] = []
        for match in ITEM_PATTERN.findall(content):
            item_id = match.strip()
            message = f"{item_id} : {target.url}<br/><br/>"
            items.append(AlertItem(item_id=item_id, message=message))
        return items


PROVIDER = SpaceweatherComProvider()

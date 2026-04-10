"""spaceweather.gov provider."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from alert.models import AlertItem, TargetConfig
from alert.providers.base import AlertProvider

ITEM_PATTERN = re.compile(
    r"(<div class=\"views-content-title\">.*?<div class=\"views-content-changed\">.*?</div>)",
    re.DOTALL,
)


class SpaceweatherGovProvider(AlertProvider):
    name = "spaceweather_gov"
    default_email_title = "spaceweather.gov Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        items: list[AlertItem] = []
        for block in ITEM_PATTERN.findall(content):
            date_match = re.search(r"<div class=\"views-content-changed\">(.+?)</div>", block, re.DOTALL)
            title_match = re.search(
                r"<div class=\"views-content-title\">.*?<a href=\"([^\"]+)\">(.+?)</a>",
                block,
                re.DOTALL,
            )
            if not title_match:
                continue

            date_str = ""
            if date_match:
                date_str = re.sub(r"<[^>]+>", "", date_match.group(1)).strip()

            title = re.sub(r"<[^>]+>", "", title_match.group(2)).strip()
            item_url = urljoin(target.url, title_match.group(1).strip())
            item_id = f"{title} - {date_str}"
            message = f"{title} : {item_url} : {date_str} : {target.url}<br/><br/>"
            items.append(AlertItem(item_id=item_id, message=message, occurred_at=date_str or None))
        return items


PROVIDER = SpaceweatherGovProvider()

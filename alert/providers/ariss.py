"""ARISS announcement provider."""

from __future__ import annotations

from html import unescape
import re

from alert.models import AlertItem, TargetConfig
from alert.providers._helpers import html_link
from alert.providers.base import AlertProvider

ITEM_PATTERN = re.compile(r'(<h3 .*?>.*?</h3>)', re.DOTALL)
LINK_PATTERN = re.compile(r"<a .*?href=['\"]([^'\"]+)['\"].*?>(.+?)</a>", re.DOTALL)


class ArissProvider(AlertProvider):
    name = "ariss"
    default_email_title = "ARISS Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        items: list[AlertItem] = []
        for block in ITEM_PATTERN.findall(content):
            match = LINK_PATTERN.search(block)
            if match is None:
                continue

            link = unescape(match.group(1).strip())
            title = unescape(re.sub(r"<.*?>", "", match.group(2)).strip())
            if not link or not title:
                continue

            items.append(
                AlertItem(
                    item_id=link,
                    message=f"{title} : {html_link(link)}<br/><br/>",
                    value=title,
                    metadata={"title": title, "url": link},
                )
            )
        return items


PROVIDER = ArissProvider()

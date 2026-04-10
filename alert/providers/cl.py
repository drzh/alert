"""Craigslist-style classifieds alert provider."""

from __future__ import annotations

from html import unescape
import re

from alert.models import AlertItem, TargetConfig
from alert.providers._helpers import html_link
from alert.providers.base import AlertProvider

ITEM_PATTERN = re.compile(r'(<li class="cl-static-search-result".*?</li>)', re.DOTALL)
TITLE_PATTERN = re.compile(r'<div class="title">(.*?)</div>', re.DOTALL)
PRICE_PATTERN = re.compile(r'<div class="price">(.*?)</div>', re.DOTALL)
URL_PATTERN = re.compile(r'<a href="([^"]+)"')


class CraigslistProvider(AlertProvider):
    name = "cl"
    default_email_title = "CL Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        items: list[AlertItem] = []
        for block in ITEM_PATTERN.findall(content):
            url_match = URL_PATTERN.search(block)
            if url_match is None:
                continue

            listing_url = unescape(url_match.group(1).strip())
            title = _first_group(TITLE_PATTERN, block) or "NA"
            price = _first_group(PRICE_PATTERN, block) or "NA"
            items.append(
                AlertItem(
                    item_id=listing_url,
                    message=(
                        f"{html_link(listing_url, title)}<br/>"
                        f"Price: {price}<br/><br/>"
                    ),
                    value=price,
                    metadata={"title": title, "price": price, "url": listing_url},
                )
            )
        return items


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return unescape(match.group(1).strip())


PROVIDER = CraigslistProvider()

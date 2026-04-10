"""Slickdeals alert provider."""

from __future__ import annotations

from html import escape, unescape
import re

from alert.models import AlertItem, TargetConfig
from alert.providers._helpers import html_link, is_blacklisted, load_blacklist_patterns
from alert.providers.base import AlertProvider

DEAL_PATTERN = re.compile(r'(<div class="dealCardListView__mainColumn".*?</div>)', re.DOTALL)
HREF_PATTERN = re.compile(r'href="([^"]+)"')
TITLE_PATTERN = re.compile(r'title="([^"]+)"')


class SlickdealsProvider(AlertProvider):
    name = "sd"
    default_email_title = "SD Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        blacklist = load_blacklist_patterns(target)
        items: list[AlertItem] = []

        for block in DEAL_PATTERN.findall(content):
            href_match = HREF_PATTERN.search(block)
            title_match = TITLE_PATTERN.search(block)
            if href_match is None or title_match is None:
                continue

            href = unescape(href_match.group(1).strip())
            title = unescape(title_match.group(1).strip())
            if not href or not title or is_blacklisted(title, blacklist):
                continue

            absolute_url = href if href.startswith("http") else f"https://slickdeals.net{href}"
            items.append(
                AlertItem(
                    item_id=href,
                    message=f"{escape(title)} : {html_link(absolute_url)}<br/><br/>",
                    value=title,
                    metadata={"title": title, "url": absolute_url},
                )
            )

        return items


PROVIDER = SlickdealsProvider()

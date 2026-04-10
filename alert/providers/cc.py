"""Credit-card style article alert provider."""

from __future__ import annotations

from html import unescape
import re

from alert.models import AlertItem, TargetConfig
from alert.providers._helpers import html_link, is_blacklisted, load_blacklist_patterns
from alert.providers.base import AlertProvider

ITEM_PATTERN = re.compile(r'<h2 class="post-entry-headline">(.*?)</h2>', re.DOTALL)
LINK_PATTERN = re.compile(r'<a href="([^"]+)">(.*?)</a>', re.DOTALL)


class CreditCardGuideProvider(AlertProvider):
    name = "cc"
    default_email_title = "CC Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        blacklist = load_blacklist_patterns(target)
        items: list[AlertItem] = []

        for block in ITEM_PATTERN.findall(content):
            match = LINK_PATTERN.search(block)
            if match is None:
                continue

            link = unescape(match.group(1).strip())
            title = unescape(re.sub(r"<.*?>", "", match.group(2)).strip())
            if not link or not title or is_blacklisted(title, blacklist):
                continue

            item_id = f"{title} {link}"
            items.append(
                AlertItem(
                    item_id=item_id,
                    message=f"{html_link(link, title)}<br/><br/>",
                    value=title,
                    metadata={"title": title, "url": link},
                )
            )

        return items


PROVIDER = CreditCardGuideProvider()

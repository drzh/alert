"""Rocket launch listing provider."""

from __future__ import annotations

from html import escape, unescape
import re
from urllib.parse import urljoin

from alert.models import AlertItem, TargetConfig
from alert.providers._helpers import html_link
from alert.providers.base import AlertProvider

ITEM_PATTERN = re.compile(
    r'(<div id="launch-\d+".+?<div class="rlt_date" style="display:inline;">.+?</div>)',
    re.DOTALL,
)
ID_PATTERN = re.compile(r'<div id="(launch-\d+)"')
DATETIME_PATTERN = re.compile(r'<div class="launch_datetime rlt_datetime" data-sortDate="(\S+?)">')
PLACE_PATTERN = re.compile(r'<meta itemprop="address" content="(.+?)">')
MISSION_PATTERN = re.compile(r'<h4 itemprop="name"><a href="(.+?)" title="(.+?)" class=')


class RocketLaunchProvider(AlertProvider):
    name = "rocketlaunch"
    default_email_title = "RocketLaunch Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        items: list[AlertItem] = []
        for block in ITEM_PATTERN.findall(content):
            launch_id = _first_group(ID_PATTERN, block) or "-"
            launch_datetime = _first_group(DATETIME_PATTERN, block) or "-"
            place = _first_group(PLACE_PATTERN, block) or "-"
            mission_match = MISSION_PATTERN.search(block)
            if mission_match is None:
                continue

            relative_url = unescape(mission_match.group(1).strip())
            mission = unescape(mission_match.group(2).strip())
            absolute_url = urljoin("https://www.rocketlaunch.live/", relative_url)
            item_id = f"{launch_id} {launch_datetime} {place} {mission}"
            items.append(
                AlertItem(
                    item_id=item_id,
                    message=(
                        f"{escape(launch_id)}<br/>"
                        f"{escape(launch_datetime)}<br/>"
                        f"{escape(place)}<br/>"
                        f"{escape(mission)}<br/>"
                        f"{html_link(absolute_url)}<br/><br/>"
                    ),
                    occurred_at=launch_datetime,
                    metadata={
                        "launch_id": launch_id,
                        "datetime": launch_datetime,
                        "place": place,
                        "mission": mission,
                        "url": absolute_url,
                    },
                )
            )
        return items


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return unescape(match.group(1).strip())


PROVIDER = RocketLaunchProvider()

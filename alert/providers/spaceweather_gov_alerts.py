"""spaceweather.gov alerts provider."""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from alert.models import AlertItem, TargetConfig
from alert.providers.base import AlertProvider

OBJECT_PATTERN = re.compile(r"\{(.+?)\}", re.MULTILINE | re.DOTALL)


class SpaceweatherGovAlertsProvider(AlertProvider):
    name = "spaceweather_gov_alerts"
    default_email_title = "spaceweather.gov Alerts"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        parsed = self._parse_json(content)
        if parsed is not None:
            items = [
                self._build_item(product_id, issue_datetime, message)
                for product_id, issue_datetime, message in self._iter_alert_triplets(parsed)
            ]
            if items:
                return items

        return self._parse_with_regex(content)

    def _parse_json(self, content: str) -> object | None:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def _iter_alert_triplets(self, node: object) -> Iterator[tuple[str, str, str]]:
        if isinstance(node, dict):
            product_id = node.get("product_id")
            issue_datetime = node.get("issue_datetime")
            message = node.get("message")
            if isinstance(product_id, str) and isinstance(issue_datetime, str) and isinstance(message, str):
                yield product_id, issue_datetime, message
            for value in node.values():
                yield from self._iter_alert_triplets(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._iter_alert_triplets(value)

    def _parse_with_regex(self, content: str) -> list[AlertItem]:
        items: list[AlertItem] = []
        for block in OBJECT_PATTERN.findall(content):
            product_id = self._regex_value(block, "product_id")
            issue_datetime = self._regex_value(block, "issue_datetime")
            message = self._regex_value(block, "message")
            if product_id and issue_datetime and message:
                items.append(self._build_item(product_id, issue_datetime, message))
        return items

    def _regex_value(self, block: str, key: str) -> str | None:
        match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', block)
        return match.group(1) if match else None

    def _build_item(self, product_id: str, issue_datetime: str, message: str) -> AlertItem:
        body = "<pre>" + message.replace("\\r\\n", "\n") + "</pre><br/>"
        body = body.replace("\\/", "/")
        return AlertItem(
            item_id=f"{product_id}_{issue_datetime}",
            message=body,
            occurred_at=issue_datetime,
            metadata={"product_id": product_id},
        )


PROVIDER = SpaceweatherGovAlertsProvider()

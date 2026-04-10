from __future__ import annotations

from alert.models import TargetConfig
from alert.providers.spaceweather_com import PROVIDER as spaceweather_com_provider
from alert.providers.spaceweather_gov import PROVIDER as spaceweather_gov_provider
from alert.providers.spaceweather_gov_alerts import PROVIDER as spaceweather_gov_alerts_provider


def test_spaceweather_com_provider_parses_strong_items() -> None:
    items = spaceweather_com_provider.parse_items(
        TargetConfig(url="https://www.spaceweather.com/"),
        '<p class="foo"><strong>Big solar flare</strong></p>',
    )

    assert len(items) == 1
    assert items[0].item_id == "<strong>Big solar flare</strong>"


def test_spaceweather_gov_provider_parses_title_date_and_link() -> None:
    items = spaceweather_gov_provider.parse_items(
        TargetConfig(url="https://www.spaceweather.gov/news"),
        """
        <div class="views-content-title"><a href="/news/test">Alert title</a>
        <div class="views-content-changed">April 7, 2026</div>
        """,
    )

    assert len(items) == 1
    assert items[0].item_id == "Alert title - April 7, 2026"
    assert "https://www.spaceweather.gov/news/test" in items[0].message


def test_spaceweather_gov_alerts_provider_parses_json_payload() -> None:
    items = spaceweather_gov_alerts_provider.parse_items(
        TargetConfig(url="https://example.com/alerts.json"),
        """
        [
          {
            "product_id": "ALT123",
            "issue_datetime": "2026-04-07T19:00:00Z",
            "message": "Line 1\\\\r\\\\nLine 2"
          }
        ]
        """,
    )

    assert len(items) == 1
    assert items[0].item_id == "ALT123_2026-04-07T19:00:00Z"
    assert "<pre>Line 1" in items[0].message

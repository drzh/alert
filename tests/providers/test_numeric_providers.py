from __future__ import annotations

from alert.models import StoredAlert, TargetConfig
from alert.providers.aurora_gfz import PROVIDER as aurora_gfz_provider
from alert.providers.bz import PROVIDER as bz_provider


def test_aurora_gfz_provider_filters_by_threshold_and_reformats_time() -> None:
    items = aurora_gfz_provider.parse_items(
        TargetConfig(url="https://example.com/aurora.csv", threshold=7),
        "Time (UTC),median\n07-04-2026 20:00,6\n08-04-2026 03:00,8\n",
    )

    assert len(items) == 1
    assert items[0].item_id == "2026-04-08 03:00"
    assert items[0].value == "8.0"


def test_aurora_gfz_provider_requires_stronger_kp_than_history() -> None:
    should_alert = aurora_gfz_provider.should_alert(
        history=[
            StoredAlert(
                source_name="aurora",
                target_url="https://example.com/aurora.csv",
                item_id="2026-04-07 20:00",
                message="older",
                value="7.0",
                occurred_at="2026-04-07 20:00",
                metadata={},
                created_at="2026-04-07T20:00:00+00:00",
            )
        ],
        item=aurora_gfz_provider.parse_items(
            TargetConfig(url="https://example.com/aurora.csv", threshold=7),
            "Time (UTC),median\n08-04-2026 03:00,8\n",
        )[0],
        target=TargetConfig(url="https://example.com/aurora.csv", threshold=7),
    )

    assert should_alert is True


def test_bz_provider_parses_header_row_json_and_builds_single_alert() -> None:
    items = bz_provider.parse_items(
        TargetConfig(url="https://example.com/bz.json", threshold=-10),
        """
        [
          ["time_tag", "bz_gsm"],
          ["2026-04-07 18:00:00.000", "-5.0"],
          ["2026-04-07 19:30:00.000", "-12.5"]
        ]
        """,
    )

    assert len(items) == 1
    assert items[0].item_id == "2026-04-07 19:30:00.000"
    assert items[0].value == "-12.5"


def test_bz_provider_requires_stronger_and_later_value() -> None:
    item = bz_provider.parse_items(
        TargetConfig(url="https://example.com/bz.json", threshold=-10),
        """
        [
          ["time_tag", "bz_gsm"],
          ["2026-04-07 21:30:00.000", "-13.0"]
        ]
        """,
    )[0]
    history = [
        StoredAlert(
            source_name="bz",
            target_url="https://example.com/bz.json",
            item_id="2026-04-07 19:30:00.000",
            message="older",
            value="-12.0",
            occurred_at="2026-04-07 19:30:00.000",
            metadata={},
            created_at="2026-04-07T19:30:00+00:00",
        )
    ]

    assert bz_provider.should_alert(history, item, TargetConfig(url="https://example.com/bz.json", threshold=-10)) is True

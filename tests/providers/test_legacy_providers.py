from __future__ import annotations

from pathlib import Path

from alert.models import StoredAlert, TargetConfig
from alert.providers.ariss import PROVIDER as ariss_provider
from alert.providers.aurora import PROVIDER as aurora_provider
from alert.providers.cc import PROVIDER as cc_provider
from alert.providers.cl import PROVIDER as cl_provider
from alert.providers.ha_comet import PROVIDER as ha_comet_provider
from alert.providers.rocketlaunch import PROVIDER as rocketlaunch_provider
from alert.providers.sd import PROVIDER as sd_provider
from alert.providers.solar_prominence import PROVIDER as solar_prominence_provider
from alert.providers.solarspot import PROVIDER as solarspot_provider


def test_sd_provider_filters_blacklist_file(tmp_path: Path) -> None:
    blacklist_file = tmp_path / "sd.black"
    blacklist_file.write_text("UPS\n", encoding="utf-8")

    items = sd_provider.parse_items(
        TargetConfig(
            url="https://slickdeals.net/search",
            options={"blacklist_file": str(blacklist_file)},
        ),
        """
        <div class="dealCardListView__mainColumn">
          <a href="/f/good" title="Atomic Clock"></a>
        </div>
        <div class="dealCardListView__mainColumn">
          <a href="/f/bad" title="UPS Label Printer"></a>
        </div>
        """,
    )

    assert len(items) == 1
    assert items[0].item_id == "/f/good"


def test_cl_provider_parses_name_price_and_url() -> None:
    items = cl_provider.parse_items(
        TargetConfig(url="https://example.com/cl"),
        """
        <li class="cl-static-search-result">
          <a href="https://example.com/post/1"></a>
          <div class="title">Small Telescope</div>
          <div class="price">$75</div>
        </li>
        """,
    )

    assert len(items) == 1
    assert items[0].item_id == "https://example.com/post/1"
    assert "Small Telescope" in items[0].message
    assert "$75" in items[0].message


def test_cc_provider_parses_headline_links() -> None:
    items = cc_provider.parse_items(
        TargetConfig(url="https://example.com/cc"),
        '<h2 class="post-entry-headline"><a href="https://example.com/post">New Bonus</a></h2>',
    )

    assert len(items) == 1
    assert items[0].item_id == "New Bonus https://example.com/post"


def test_ariss_provider_accepts_single_quoted_href() -> None:
    items = ariss_provider.parse_items(
        TargetConfig(url="https://example.com/ariss"),
        "<h3 class='post'><a href='https://example.com/pass'>ISS School Contact</a></h3>",
    )

    assert len(items) == 1
    assert items[0].item_id == "https://example.com/pass"


def test_ha_comet_provider_requires_brighter_repeat_value() -> None:
    item = ha_comet_provider.parse_items(
        TargetConfig(url="https://example.com/comets", threshold=6),
        """
        <tr><td><a href="comet.aspx?id=123">C/2026 A1</a></td><td>5.0</td></tr>
        """,
    )[0]
    history = [
        StoredAlert(
            source_name="ha_comet",
            target_url="https://example.com/comets",
            item_id="C/2026 A1:5.5",
            message="older",
            value="5.5",
            occurred_at=None,
            metadata={"stable_id": "C/2026 A1"},
            created_at="2026-04-07T19:00:00+00:00",
        )
    ]

    assert ha_comet_provider.should_alert(history, item, TargetConfig(url="https://example.com/comets", threshold=6)) is True


def test_rocketlaunch_provider_parses_launch_listing() -> None:
    items = rocketlaunch_provider.parse_items(
        TargetConfig(url="https://example.com/launches"),
        """
        <div id="launch-123">
          <div class="launch_datetime rlt_datetime" data-sortDate="2026-04-08T01:00:00Z"></div>
          <meta itemprop="address" content="Cape Canaveral">
          <h4 itemprop="name"><a href="/launch/test" title="Falcon 9 Starlink" class="foo"></a></h4>
          <div class="rlt_date" style="display:inline;"></div>
        </div>
        """,
    )

    assert len(items) == 1
    assert items[0].item_id == "launch-123 2026-04-08T01:00:00Z Cape Canaveral Falcon 9 Starlink"
    assert "https://www.rocketlaunch.live/launch/test" in items[0].message


def test_aurora_provider_uses_state_file_and_writes_table(tmp_path: Path) -> None:
    state_file = tmp_path / "aurora.val"
    state_file.write_text("threehr_max\t4\nday1_max\t0\nday2_max\t0\nday3_max\t0\n", encoding="utf-8")
    table_file = tmp_path / "aurora.3day.txt"
    content = """
The greatest expected 3 hr Kp for Apr 10-Apr 12 2026 is 4.67 (NOAA Scale
G1).

NOAA Kp index breakdown Apr 10-Apr 12 2026

             Apr 10       Apr 11       Apr 12
00-03UT       4.00         3.67         3.67
03-06UT       2.67         4.67 (G1)    3.67
06-09UT       2.67         4.00         3.67
09-12UT       2.00         3.67         2.67
12-15UT       3.67         2.67         2.67
15-18UT       2.67         2.67         1.67
18-21UT       4.00         4.00         2.67
21-00UT       4.67 (G1)    4.67 (G1)    3.00
"""
    target = TargetConfig(
        url="https://services.swpc.noaa.gov/text/3-day-forecast.txt",
        threshold=4.5,
        options={"state_file": str(state_file), "table_output_file": str(table_file)},
    )

    items = aurora_provider.parse_items(target, content)
    pending = [item for item in items if aurora_provider.should_alert([], item, target)]
    aurora_provider.after_target(
        target,
        items,
        pending,
        content,
        persist=True,
        notification_sent=True,
    )

    assert any(item.metadata.get("stable_id") == "threehr_max" and item.value == "4.67" for item in pending)
    assert any(item.metadata.get("stable_id") == "day1_max" and item.value == "4.67" for item in pending)
    assert any(item.metadata.get("stable_id") == "day2_max" and item.value == "4.67" for item in pending)
    assert "threehr_max\t4.67" in state_file.read_text(encoding="utf-8")
    assert "00-03UT" in table_file.read_text(encoding="utf-8")
    assert "03-06UT       2.67         4.67 (G1)    3.67" in table_file.read_text(encoding="utf-8")


def test_solarspot_provider_updates_state_on_alert(tmp_path: Path) -> None:
    state_file = tmp_path / "solarspot.val"
    state_file.write_text("max\t700\n", encoding="utf-8")
    target = TargetConfig(
        url="https://services.swpc.noaa.gov/text/srs.txt",
        threshold=700,
        options={"state_file": str(state_file)},
    )
    content = """
Header
Nmbr Location Lo Area Z LL NN Mag Type
1234 N10W10 100 750 B 12 01 Beta
IA. End
"""

    items = solarspot_provider.parse_items(target, content)
    assert len(items) == 1
    assert solarspot_provider.should_alert([], items[0], target) is True

    solarspot_provider.after_target(
        target,
        items,
        items,
        content,
        persist=True,
        notification_sent=True,
    )

    assert state_file.read_text(encoding="utf-8").strip() == "max\t750"


def test_solar_prominence_provider_compares_and_updates_state(tmp_path: Path) -> None:
    state_file = tmp_path / "prominence.old"
    state_file.write_text(
        "\n".join(
            [
                "current_time\t2026-04-07T19:00:00",
                "prominence_max_distance_pixels\t100",
                "prominence_area_pixels\t1500",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    attachment_file = tmp_path / "prominence.png"
    attachment_file.write_bytes(b"png")
    target = TargetConfig(
        url=(tmp_path / "prominence.txt").resolve().as_uri(),
        options={
            "state_file": str(state_file),
            "attachment_path": str(attachment_file),
            "time_threshold_minutes": 10,
            "distance_threshold": 20,
            "area_threshold": 1000,
        },
    )
    content = "\n".join(
        [
            "current_time\t2026-04-07T19:20:00",
            "prominence_max_distance_pixels\t180",
            "prominence_area_pixels\t2200",
        ]
    )

    items = solar_prominence_provider.parse_items(target, content)
    assert len(items) == 1
    assert len(items[0].attachments) == 1
    assert solar_prominence_provider.should_alert([], items[0], target) is True

    solar_prominence_provider.after_target(
        target,
        items,
        items,
        content,
        persist=True,
        notification_sent=True,
    )

    assert "2026-04-07T19:20:00" in state_file.read_text(encoding="utf-8")


def test_solar_prominence_provider_removes_stale_state_after_no_alert(tmp_path: Path) -> None:
    state_file = tmp_path / "prominence.old"
    state_file.write_text(
        "\n".join(
            [
                "current_time\t2026-04-07T18:00:00",
                "prominence_max_distance_pixels\t300",
                "prominence_area_pixels\t5000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    target = TargetConfig(
        url=(tmp_path / "prominence.txt").resolve().as_uri(),
        options={
            "state_file": str(state_file),
            "remove_threshold_minutes": 60,
            "distance_threshold": 20,
            "area_threshold": 1000,
        },
    )
    content = "\n".join(
        [
            "current_time\t2026-04-07T20:30:00",
            "prominence_max_distance_pixels\t100",
            "prominence_area_pixels\t100",
        ]
    )
    items = solar_prominence_provider.parse_items(target, content)

    solar_prominence_provider.after_target(
        target,
        items,
        (),
        content,
        persist=True,
        notification_sent=False,
    )

    assert state_file.exists() is False

from __future__ import annotations

from pathlib import Path

from alert.infra.repository import AlertRepository
from alert.models import AlertItem


def test_repository_saves_and_loads_alert_history(tmp_path: Path) -> None:
    repository = AlertRepository(str(tmp_path / "alerts.db"))
    try:
        inserted = repository.save_alerts(
            "bz",
            "https://example.com/bz.json",
            [
                AlertItem(item_id="one", message="first", value="-10", occurred_at="2026-01-01T00:00:00"),
                AlertItem(item_id="two", message="second", value="-12", occurred_at="2026-01-01T01:00:00"),
            ],
        )
        history = repository.get_history("bz", "https://example.com/bz.json")
    finally:
        repository.close()

    assert inserted == 2
    assert [item.item_id for item in history] == ["two", "one"]
    assert history[0].value == "-12"


def test_repository_ignores_duplicates_and_prunes_per_target(tmp_path: Path) -> None:
    repository = AlertRepository(str(tmp_path / "alerts.db"))
    try:
        repository.save_alerts(
            "aurora",
            "https://example.com/a.csv",
            [AlertItem(item_id="one", message="first", value="7")],
        )
        duplicate_count = repository.save_alerts(
            "aurora",
            "https://example.com/a.csv",
            [AlertItem(item_id="one", message="first", value="7")],
        )
        repository.save_alerts(
            "aurora",
            "https://example.com/a.csv",
            [AlertItem(item_id="two", message="second", value="8")],
        )
        pruned = repository.prune("aurora", "https://example.com/a.csv", keep=1)
        history = repository.get_history("aurora", "https://example.com/a.csv")
    finally:
        repository.close()

    assert duplicate_count == 0
    assert pruned == 1
    assert [item.item_id for item in history] == ["two"]

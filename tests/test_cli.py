from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import alert.cli as cli
from alert.models import AppConfig, RunSummary, SourceConfig, TargetConfig


@dataclass
class FakeRunner:
    seen_sources: list[str] = field(default_factory=list)

    def run_source(self, source: SourceConfig, persist: bool = True) -> RunSummary:
        self.seen_sources.append(source.name)
        return RunSummary(
            source_name=source.name,
            targets_checked=len(source.targets),
            items_seen=0,
            alerts_triggered=0,
            alerts_saved=0,
            notification_sent=False,
            dry_run=not persist,
        )


def test_cli_list_providers_outputs_known_provider(capsys) -> None:
    exit_code = cli.main(["list-providers"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "bz" in output


def test_cli_run_all_invokes_each_source(monkeypatch, capsys) -> None:
    config = AppConfig(
        sources=(
            SourceConfig(name="one", provider="spaceweather_com", db_file="one.db", targets=(TargetConfig(url="https://one"),)),
            SourceConfig(name="two", provider="bz", db_file="two.db", targets=(TargetConfig(url="https://two"),)),
        ),
        smtp=None,
    )
    fake_runner = FakeRunner()

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "AlertRunner", lambda http_client, notifier: fake_runner)

    exit_code = cli.main(["run", "--config", "alerts.toml", "--all", "--dry-run"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert fake_runner.seen_sources == ["one", "two"]
    assert "source=one" in output
    assert "source=two" in output


def test_cli_requires_smtp_when_not_dry_run(monkeypatch) -> None:
    config = AppConfig(
        sources=(SourceConfig(name="one", provider="spaceweather_com", db_file="one.db", targets=(TargetConfig(url="https://one"),)),),
        smtp=None,
    )
    monkeypatch.setattr(cli, "load_config", lambda path: config)

    with pytest.raises(ValueError):
        cli.main(["run", "--config", "alerts.toml", "--source", "one"])

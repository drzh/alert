from __future__ import annotations

from pathlib import Path

from alert.config import load_config


def test_load_config_supports_multiple_targets_per_source(tmp_path: Path) -> None:
    config_path = tmp_path / "alerts.toml"
    config_path.write_text(
        """
[smtp]
host = "smtp.gmail.com"
port = 587
username = "user@example.com"
password_env = "ALERT_SMTP_PASSWORD"
sender = "user@example.com"
recipients = ["user@example.com"]

[[sources]]
name = "bz"
provider = "bz"
db_file = "state/bz.db"

[[sources.targets]]
url = "https://example.com/a.json"
threshold = -10

[[sources.targets]]
url = "https://example.com/b.json"
threshold = -15
timeout_seconds = 45
""",
        encoding="utf-8",
    )

    config = load_config(config_path)
    source = config.get_source("bz")

    assert config.smtp is not None
    assert config.smtp.password_env == "ALERT_SMTP_PASSWORD"
    assert source.provider == "bz"
    assert source.db_file == str((tmp_path / "state" / "bz.db").resolve())
    assert len(source.targets) == 2
    assert source.targets[0].threshold == -10
    assert source.targets[1].threshold == -15
    assert source.targets[1].timeout_seconds == 45


def test_load_config_defaults_db_file_to_source_name(tmp_path: Path) -> None:
    config_path = tmp_path / "alerts.toml"
    config_path.write_text(
        """
[[sources]]
name = "spaceweather_com"
provider = "spaceweather_com"

[[sources.targets]]
url = "https://example.com/"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)
    source = config.get_source("spaceweather_com")

    assert source.db_file == str((tmp_path / "spaceweather_com.db").resolve())


def test_load_config_resolves_relative_option_paths_and_local_target_urls(tmp_path: Path) -> None:
    config_path = tmp_path / "alerts.toml"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "current.txt").write_text("current_time\t2026-04-07T20:00:00\n", encoding="utf-8")

    config_path.write_text(
        """
[[sources]]
name = "solar_prominence"
provider = "solar_prominence"

[[sources.targets]]
url = "./data/current.txt"
state_file = "state/solar_prominence.txt"
attachment_path = "images/prominence.png"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)
    target = config.get_source("solar_prominence").targets[0]

    assert target.url == (tmp_path / "data" / "current.txt").resolve().as_uri()
    assert target.options["state_file"] == str((tmp_path / "state" / "solar_prominence.txt").resolve())
    assert target.options["attachment_path"] == str((tmp_path / "images" / "prominence.png").resolve())

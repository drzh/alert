from __future__ import annotations

from types import SimpleNamespace

import pytest

from alert.models import TargetConfig
from alert.providers.atmospheric_optics import PROVIDER as atmospheric_optics_provider


def test_atmospheric_optics_provider_runs_local_predictor(monkeypatch, tmp_path) -> None:
    project_dir = tmp_path / "atmospheric_optics"
    cli_dir = project_dir / "cli"
    cli_dir.mkdir(parents=True)
    (cli_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"halo": 0.91, "sources": []}', stderr="")

    monkeypatch.setattr("alert.providers.atmospheric_optics.subprocess.run", fake_run)

    content = atmospheric_optics_provider.fetch_content(
        TargetConfig(
            url="atmospheric-optics://home",
            threshold=0.8,
            timeout_seconds=45.0,
            options={
                "lat": 32.82,
                "lon": -96.82,
                "mode": "observed",
                "project_dir": str(project_dir),
                "python_path": "/usr/bin/python3",
                "download_dir": str(tmp_path / "cache"),
            },
        ),
        http_client=object(),
    )

    assert content == '{"halo": 0.91, "sources": []}'
    assert captured["command"] == [
        "/usr/bin/python3",
        str(cli_dir / "main.py"),
        "--lat",
        "32.82",
        "--lon",
        "-96.82",
        "--mode",
        "observed",
        "--keep-downloaded-files",
        "--download-dir",
        str(tmp_path / "cache"),
    ]
    assert captured["cwd"] == project_dir
    assert captured["timeout"] == 45.0


def test_atmospheric_optics_provider_filters_by_threshold_and_selected_phenomena() -> None:
    items = atmospheric_optics_provider.parse_items(
        TargetConfig(
            url="atmospheric-optics://home",
            threshold=0.8,
            options={
                "lat": 32.82,
                "lon": -96.82,
                "mode": "observed",
                "phenomena": ["halo", "rainbow"],
            },
        ),
        """
        {
          "halo": 0.842,
          "parhelia": 0.913,
          "cza": 0.901,
          "rainbow": 0.245,
          "sources": [
            {"name": "goes-east", "timestamp": "20260407 124617z"},
            {"name": "metar", "timestamp": "20260407 1953z"}
          ]
        }
        """,
    )

    assert len(items) == 1
    assert items[0].item_id == "halo:observed:goes-east@20260407 124617z|metar@20260407 1953z"
    assert items[0].value == "0.842"
    assert items[0].metadata["phenomenon"] == "halo"
    assert "Sources: goes-east 20260407 124617z, metar 20260407 1953z" in items[0].message


def test_atmospheric_optics_provider_rejects_invalid_phenomena() -> None:
    with pytest.raises(ValueError):
        atmospheric_optics_provider.parse_items(
            TargetConfig(
                url="atmospheric-optics://home",
                options={
                    "lat": 32.82,
                    "lon": -96.82,
                    "phenomena": ["halo", "glory"],
                },
            ),
            '{"halo": 0.9, "sources": []}',
        )

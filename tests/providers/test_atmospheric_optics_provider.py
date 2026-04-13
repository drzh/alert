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
        return SimpleNamespace(returncode=0, stdout='{"phenomena": [], "sources": []}', stderr="")

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
                "at_time": "2026-04-13T18:00:00Z",
                "time_window_hours": [0, 1, 3],
                "phenomena": ["halo", "rainbow"],
            },
        ),
        http_client=object(),
    )

    assert content == '{"phenomena": [], "sources": []}'
    assert captured["command"] == [
        "/usr/bin/python3",
        str(cli_dir / "main.py"),
        "--lat",
        "32.82",
        "--lon",
        "-96.82",
        "--mode",
        "observed",
        "--at-time",
        "2026-04-13T18:00:00Z",
        "--time-window-hours",
        "0,1,3",
        "--phenomena",
        "halo,rainbow",
        "--keep-downloaded-files",
        "--download-dir",
        str(tmp_path / "cache"),
    ]
    assert captured["cwd"] == project_dir
    assert captured["timeout"] == 45.0


def test_atmospheric_optics_provider_filters_by_peak_threshold_and_selected_phenomena() -> None:
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
          "request": {
            "mode": "observed",
            "prediction_time": "2026-04-13T18:00:00Z",
            "location": {"lat": 32.82, "lon": -96.82}
          },
          "phenomena": [
            {
              "id": "halo",
              "label": "Halo",
              "category": "ice_crystal",
              "current": {
                "probability": 0.442,
                "confidence": 0.913,
                "reason": "Thin cirrus with favorable solar elevation",
                "spatial_context": {
                  "radius_km": 40.0,
                  "aggregation": "weighted_blend",
                  "mean_probability": 0.523,
                  "max_probability": 0.842,
                  "spatial_variance": 0.014
                }
              },
              "peak": {
                "probability": 0.842,
                "time": "2026-04-13T19:00:00Z"
              },
              "timeline": [
                {"label": "now", "offset_hours": 0, "probability": 0.442},
                {"label": "1h", "offset_hours": 1, "probability": 0.842}
              ]
            },
            {
              "id": "rainbow",
              "label": "Rainbow",
              "category": "water_droplet",
              "current": {
                "probability": 0.245,
                "confidence": 0.655,
                "reason": "rainbow reason"
              },
              "peak": {
                "probability": 0.4,
                "time": "2026-04-13T19:00:00Z"
              },
              "timeline": [
                {"label": "now", "offset_hours": 0, "probability": 0.245},
                {"label": "1h", "offset_hours": 1, "probability": 0.4}
              ]
            }
          ],
          "sources": [
            {"id": "goes-east", "label": "GOES East", "kind": "satellite", "timestamp": "20260407 124617z"},
            {"id": "metar", "label": "METAR", "kind": "surface_observation", "timestamp": "20260407 1953z"}
          ]
        }
        """,
    )

    assert len(items) == 1
    assert items[0].item_id == "halo:observed:goes-east@20260407 124617z|metar@20260407 1953z"
    assert items[0].value == "0.842"
    assert items[0].occurred_at == "2026-04-13T19:00:00Z"
    assert items[0].metadata["phenomenon"] == "halo"
    assert items[0].metadata["label"] == "Halo"
    assert items[0].metadata["category"] == "ice_crystal"
    assert items[0].metadata["probability"] == pytest.approx(0.842)
    assert items[0].metadata["current_probability"] == pytest.approx(0.442)
    assert items[0].metadata["peak_time"] == "2026-04-13T19:00:00Z"
    assert items[0].metadata["confidence"] == pytest.approx(0.913)
    assert items[0].metadata["reason"] == "Thin cirrus with favorable solar elevation"
    assert items[0].metadata["spatial_context"]["aggregation"] == "weighted_blend"
    assert "Current probability: 0.442" in items[0].message
    assert "Peak probability 0.842" not in items[0].message
    assert "peak probability 0.842" in items[0].message
    assert "Peak time: 2026-04-13T19:00:00Z" in items[0].message
    assert "Prediction time: 2026-04-13T18:00:00Z" in items[0].message


def test_atmospheric_optics_provider_rejects_unknown_selected_phenomena() -> None:
    with pytest.raises(ValueError):
        atmospheric_optics_provider.parse_items(
            TargetConfig(
                url="atmospheric-optics://home",
                options={
                    "lat": 32.82,
                    "lon": -96.82,
                    "phenomena": ["glory"],
                },
            ),
            '{"phenomena": [{"id": "halo", "label": "Halo", "current": {"probability": 0.9}, "peak": {"probability": 0.9, "time": "2026-04-13T18:00:00Z"}, "timeline": []}], "sources": []}',
        )


def test_atmospheric_optics_provider_accepts_payload_defined_future_phenomena() -> None:
    items = atmospheric_optics_provider.parse_items(
        TargetConfig(
            url="atmospheric-optics://home",
            threshold=0.8,
            options={
                "lat": 32.82,
                "lon": -96.82,
                "mode": "observed",
                "phenomena": ["glory"],
            },
        ),
        """
        {
          "request": {
            "mode": "observed",
            "prediction_time": "2026-04-13T18:00:00Z",
            "location": {"lat": 32.82, "lon": -96.82}
          },
          "phenomena": [
            {
              "id": "glory",
              "label": "Glory",
              "category": "water_droplet",
              "current": {
                "probability": 0.701,
                "confidence": 0.701,
                "reason": "Backscattered droplets support a glory.",
                "spatial_context": {
                  "radius_km": 8.0,
                  "aggregation": "weighted_blend",
                  "mean_probability": 0.744,
                  "max_probability": 0.901,
                  "spatial_variance": 0.008
                }
              },
              "peak": {
                "probability": 0.901,
                "time": "2026-04-13T19:00:00Z"
              },
              "timeline": [
                {"label": "now", "offset_hours": 0, "probability": 0.701},
                {"label": "1h", "offset_hours": 1, "probability": 0.901}
              ]
            }
          ],
          "sources": [
            {"id": "goes-east", "label": "GOES East", "kind": "satellite", "timestamp": "20260407 124617z"},
            {"id": "metar", "label": "METAR", "kind": "surface_observation", "timestamp": "20260407 1953z"}
          ]
        }
        """,
    )

    assert [item.metadata["phenomenon"] for item in items] == ["glory"]
    assert items[0].item_id == "glory:observed:goes-east@20260407 124617z|metar@20260407 1953z"
    assert items[0].metadata["label"] == "Glory"
    assert items[0].metadata["spatial_context"]["aggregation"] == "weighted_blend"
    assert "Glory" in items[0].message
    assert "Peak time:" in items[0].message

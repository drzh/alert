from __future__ import annotations

from types import SimpleNamespace

from alert.models import TargetConfig
from export_atmospheric_optics_json import _build_export_payload, _target_with_illumination_override


def test_build_export_payload_wraps_prediction_and_preserves_flexible_structure() -> None:
    source = SimpleNamespace(name="atmospheric_optics")
    target = SimpleNamespace(
        name="Home",
        threshold=0.8,
        options={
            "mode": "observed",
            "lat": 32.847,
            "lon": -96.806,
            "phenomena": ["halo", "fogbow"],
        },
    )
    raw_payload = {
        "generated_at": "2026-04-13T17:00:00Z",
        "request": {
            "location": {"lat": 32.8471, "lon": -96.8059},
            "mode": "forecast",
            "prediction_time": "2026-04-13T18:00:00Z",
            "time_window_hours": [0, 1, 3],
            "options": {
                "lightweight": False,
                "debug": False,
                "phenomena": ["halo", "fogbow"],
            },
        },
        "phenomena": [
            {
                "id": "halo",
                "label": "Halo",
                "category": "ice_crystal",
                "current": {
                    "probability": 0.12345,
                    "confidence": 0.91234,
                    "confidence_components": {
                        "data": 0.9012,
                    },
                    "reason": "halo reason",
                    "spatial_context": {
                        "radius_km": 40.0,
                        "aggregation": "weighted_blend",
                        "mean_probability": 0.1542,
                        "max_probability": 0.2042,
                    },
                },
                "peak": {
                    "probability": 0.2042,
                    "time": "2026-04-13T19:00:00Z",
                },
                "timeline": [
                    {"label": "now", "offset_hours": 0, "probability": 0.12345},
                    {"label": "1h", "offset_hours": 1, "probability": 0.2042},
                ],
            },
            {
                "id": "fogbow",
                "label": "Fogbow",
                "category": "water_droplet",
                "current": {
                    "probability": 0.9678,
                    "confidence": 0.79,
                    "reason": "fogbow reason",
                },
                "peak": {
                    "probability": 0.9678,
                    "time": "2026-04-13T18:00:00Z",
                },
                "timeline": [
                    {"label": "now", "offset_hours": 0, "probability": 0.9678},
                ],
            },
        ],
        "sources": [{"id": "goes-east", "label": "GOES East", "kind": "satellite", "timestamp": "20260413 155618z"}],
    }

    result = _build_export_payload(source, target, raw_payload)

    assert result["source"] == {"name": "atmospheric_optics"}
    assert result["target"] == {
        "name": "Home",
        "threshold": 0.8,
        "location": {"lat": 32.847, "lon": -96.806},
        "mode": "observed",
        "phenomena": ["halo", "fogbow"],
    }
    assert result["exported_at"].endswith("Z")
    assert result["prediction"]["request"]["mode"] == "forecast"
    assert result["prediction"]["request"]["prediction_time"] == "2026-04-13T18:00:00Z"
    assert result["prediction"]["request"]["time_window_hours"] == [0, 1, 3]
    assert result["prediction"]["phenomena"][0]["current"]["probability"] == 0.123
    assert result["prediction"]["phenomena"][0]["current"]["confidence"] == 0.912
    assert result["prediction"]["phenomena"][0]["current"]["spatial_context"]["mean_probability"] == 0.154
    assert result["prediction"]["phenomena"][0]["timeline"][0]["probability"] == 0.123
    assert result["prediction"]["phenomena"][1]["current"]["reason"] == "fogbow reason"
    assert result["prediction"]["sources"] == [
        {"id": "goes-east", "label": "GOES East", "kind": "satellite", "timestamp": "20260413 155618z"}
    ]


def test_build_export_payload_preserves_target_illumination_when_present() -> None:
    source = SimpleNamespace(name="atmospheric_optics")
    target = SimpleNamespace(
        name="Moon",
        threshold=0.6,
        options={
            "mode": "observed",
            "illumination": "lunar",
            "lat": 32.847,
            "lon": -96.806,
        },
    )

    result = _build_export_payload(source, target, {"request": {}, "phenomena": [], "sources": []})

    assert result["target"]["mode"] == "observed"
    assert result["target"]["location"] == {"lat": 32.847, "lon": -96.806}
    assert result["target"]["illumination"] == "lunar"


def test_target_with_illumination_override_updates_target_options() -> None:
    target = TargetConfig(
        url="atmospheric-optics://home",
        name="Home",
        threshold=0.8,
        options={
            "mode": "observed",
            "illumination": "solar",
            "lat": 32.847,
            "lon": -96.806,
        },
    )

    overridden = _target_with_illumination_override(target, "lunar")

    assert overridden is not target
    assert overridden.options["illumination"] == "lunar"

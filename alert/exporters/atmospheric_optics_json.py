#!/usr/bin/env python3
"""Export the configured atmospheric optics payload to a JSON file."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from datetime import datetime, timezone
from pathlib import Path

from alert.config import load_config
from alert.models import TargetConfig
from alert.providers.atmospheric_optics import PROVIDER

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUND_DECIMALS = 3
DEFAULT_ILLUMINATION = "solar,lunar"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "alerts.toml"),
        help="Alert TOML config path.",
    )
    parser.add_argument(
        "--source",
        default="atmospheric_optics",
        help="Source name to export.",
    )
    parser.add_argument(
        "--target-name",
        default="",
        help="Optional target name. Defaults to the first target in the source.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file path.",
    )
    parser.add_argument(
        "--prediction-only",
        action="store_true",
        help="Write the raw predictor payload instead of the wrapped export envelope.",
    )
    parser.add_argument(
        "--illumination",
        choices=("solar", "lunar", DEFAULT_ILLUMINATION),
        help="Optional illumination override for the exported predictor run.",
    )
    return parser


def _select_source(config_path: Path, source_name: str):
    config = load_config(config_path)
    for source in config.sources:
        if source.name == source_name:
            return source
    raise ValueError(f"Source not found in config: {source_name}")


def _select_target(source, target_name: str):
    if target_name:
        for target in source.targets:
            if (target.name or "") == target_name:
                return target
        raise ValueError(f"Target not found in source '{source.name}': {target_name}")
    return source.targets[0]


def _option_parts(options: dict[str, object], key: str) -> list[str]:
    value = options.get(key)
    if value is None:
        return []
    raw_values = value if isinstance(value, (list, tuple)) else (value,)
    parts: list[str] = []
    for raw_value in raw_values:
        for part in str(raw_value).split(","):
            normalized = part.strip()
            if normalized:
                parts.append(normalized)
    return parts


def _target_locations(options: dict[str, object]) -> list[dict[str, object]]:
    latitudes = _option_parts(options, "lat") or ["0.0"]
    longitudes = _option_parts(options, "lon") or ["0.0"]
    if len(latitudes) != len(longitudes):
        raise ValueError("atmospheric_optics lat/lon target options must have the same length.")

    sites = _option_parts(options, "site")
    if not sites:
        sites = ["NA" for _ in latitudes]
    if len(sites) != len(latitudes):
        raise ValueError("atmospheric_optics site target option must match lat/lon length.")

    locations: list[dict[str, object]] = []
    for index, latitude in enumerate(latitudes):
        location: dict[str, object] = {
            "lat": float(latitude),
            "lon": float(longitudes[index]),
        }
        site = sites[index]
        if site and site.upper() != "NA":
            location["site"] = site
        locations.append(location)
    return locations


def _normalize_target(target) -> dict[str, object]:
    options = target.options
    locations = _target_locations(options)
    normalized = {
        "name": target.name or "",
        "threshold": float(target.threshold) if target.threshold is not None else None,
        "mode": str(options.get("mode", "observed")),
    }
    if len(locations) == 1:
        normalized["location"] = locations[0]
    else:
        normalized["locations"] = locations
    if "illumination" in options:
        normalized["illumination"] = str(options.get("illumination", DEFAULT_ILLUMINATION))
    configured_phenomena = options.get("phenomena")
    if isinstance(configured_phenomena, (list, tuple)):
        normalized["phenomena"] = [
            str(value).strip()
            for value in configured_phenomena
            if str(value).strip()
        ]
    return normalized


def _round_numbers(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _round_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_numbers(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, ROUND_DECIMALS)
    return value


def _build_export_payload(source, target, payload: dict[str, object]) -> dict[str, object]:
    return {
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {
            "name": source.name,
        },
        "target": _normalize_target(target),
        "prediction": _round_numbers(payload),
    }


def _target_with_illumination_override(target: TargetConfig, illumination: str | None) -> TargetConfig:
    if not illumination:
        return target
    updated_options = dict(target.options)
    previous_illumination = str(updated_options.get("illumination", DEFAULT_ILLUMINATION)).strip().lower()
    updated_options["illumination"] = illumination
    if previous_illumination != illumination and "phenomena" in updated_options:
        updated_options.pop("phenomena", None)
    return replace(target, options=updated_options)


def write_json(output_path: Path, payload: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(output_path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    source = _select_source(config_path, args.source)
    target = _target_with_illumination_override(
        _select_target(source, args.target_name.strip()),
        args.illumination,
    )
    content = PROVIDER.fetch_content(target, http_client=object())
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("Atmospheric optics payload must be a JSON object.")

    export_payload = payload if args.prediction_only else _build_export_payload(source, target, payload)
    write_json(output_path, export_payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

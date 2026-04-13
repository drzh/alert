#!/usr/bin/env python3
"""Export the configured atmospheric optics payload to a JSON file."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alert.config import load_config
from alert.providers.atmospheric_optics import PROVIDER

ROUND_DECIMALS = 3


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


def _normalize_target(target) -> dict[str, object]:
    options = target.options
    normalized = {
        "name": target.name or "",
        "threshold": float(target.threshold) if target.threshold is not None else None,
        "location": {
            "lat": float(options.get("lat", 0.0)),
            "lon": float(options.get("lon", 0.0)),
        },
        "mode": str(options.get("mode", "observed")),
    }
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
    target = _select_target(source, args.target_name.strip())
    content = PROVIDER.fetch_content(target, http_client=object())
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("Atmospheric optics payload must be a JSON object.")

    write_json(output_path, _build_export_payload(source, target, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

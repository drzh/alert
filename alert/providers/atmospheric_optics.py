"""Atmospheric optics provider backed by the sibling predictor repo."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from alert.config import load_config
from alert.models import AlertItem, SourceConfig, TargetConfig
from alert.providers._helpers import option_str
from alert.providers.base import AlertProvider

WEATHER_MODES = {"forecast", "observed"}
ILLUMINATION_MODES = {"solar", "lunar"}
DEFAULT_ILLUMINATION = "solar,lunar"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUND_DECIMALS = 3
LUNAR_PHENOMENA = {
    "lunar_halo",
    "paraselenae",
    "lunar_pillar",
    "lunar_corona",
    "moonbow",
}
DEFAULT_PROJECT_DIR = Path(__file__).resolve().parents[3] / "atmospheric_optics"
PREDICTOR_CLI = Path("cli") / "command.py"


class AtmosphericOpticsProvider(AlertProvider):
    name = "atmospheric_optics"
    default_email_title = "Atmospheric Optics Alert"

    def fetch_content(self, target: TargetConfig, http_client: object) -> str:
        del http_client

        locations = _resolve_locations(target)
        mode = _resolve_mode(target)
        illumination = _resolve_illumination(target)
        project_dir = _resolve_project_dir(target)
        cli_path = project_dir / PREDICTOR_CLI
        if not cli_path.is_file():
            raise FileNotFoundError(f"atmospheric_optics CLI not found: {cli_path}")

        python_path = option_str(target, "python_path") or sys.executable
        download_dir = option_str(target, "download_dir")
        at_time = option_str(target, "at_time")
        time_window_hours = _option_csv(target, "time_window_hours")
        phenomena = _option_csv(target, "phenomena")
        spatial_resolution_km = option_str(target, "spatial_resolution_km")
        lightweight = _option_bool(target, "lightweight", default=False)
        debug = _option_bool(target, "debug", default=False)
        keep_downloaded_files = _option_bool(
            target,
            "keep_downloaded_files",
            default=bool(download_dir),
        )
        lat_values = _join_csv(location["lat"] for location in locations)
        lon_values = _join_csv(location["lon"] for location in locations)
        command = [
            python_path,
            str(cli_path),
            "--lat",
            lat_values,
        ]
        if lon_values.startswith("-") and "," in lon_values:
            command.append(f"--lon={lon_values}")
        else:
            command.extend(["--lon", lon_values])
        command.extend(["--mode", mode])
        if _location_sites_configured(target):
            command.extend(["--site", _join_csv(location["site"] for location in locations)])
        command.extend(["--illumination", illumination])
        if at_time:
            command.extend(["--at-time", at_time])
        if time_window_hours:
            command.extend(["--time-window-hours", time_window_hours])
        if phenomena:
            command.extend(["--phenomena", phenomena])
        if spatial_resolution_km:
            command.extend(["--spatial-resolution-km", spatial_resolution_km])
        if lightweight:
            command.append("--lightweight")
        if debug:
            command.append("--debug")
        if keep_downloaded_files:
            command.append("--keep-downloaded-files")
        if download_dir:
            command.extend(["--download-dir", download_dir])

        completed = subprocess.run(
            command,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=target.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
            raise RuntimeError(f"atmospheric_optics command failed: {detail}")
        return completed.stdout

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        payload = _parse_payload(content)
        items: list[AlertItem] = []
        for prediction_payload, site_hint in _prediction_payloads(payload):
            items.extend(_parse_prediction_items(target, prediction_payload, site_hint))
        return items

    def build_subject(
        self,
        source: SourceConfig,
        alerts_by_target: dict[str, list[AlertItem]],
    ) -> str:
        labels: list[str] = []
        for alerts in alerts_by_target.values():
            for alert in alerts:
                label = _to_string(alert.metadata.get("label"))
                if label and label not in labels:
                    labels.append(label)

        subject = source.resolved_email_title(self.default_email_title)
        if not labels:
            return subject
        return f"{subject}: {', '.join(labels)}"


def normalize_target_for_export(target: TargetConfig) -> dict[str, object]:
    locations = tuple(_export_location(location) for location in _resolve_locations(target))
    normalized: dict[str, object] = {
        "name": target.name or "",
        "threshold": float(target.threshold) if target.threshold is not None else None,
        "mode": _resolve_mode(target),
    }
    if len(locations) == 1:
        normalized["location"] = locations[0]
    else:
        normalized["locations"] = list(locations)
    if "illumination" in target.options:
        normalized["illumination"] = _resolve_illumination(target)

    configured_phenomena = target.options.get("phenomena")
    if isinstance(configured_phenomena, (list, tuple)):
        normalized["phenomena"] = [
            str(value).strip()
            for value in configured_phenomena
            if str(value).strip()
        ]
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export the configured atmospheric optics payload to a JSON file."
    )
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
        "target": normalize_target_for_export(target),
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


def _export_location(location: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {
        "lat": float(location["lat"]),
        "lon": float(location["lon"]),
    }
    site = _meaningful_site(_to_string(location.get("site")))
    if site:
        normalized["site"] = site
    return normalized


def _parse_prediction_items(
    target: TargetConfig,
    payload: dict[str, object],
    site_hint: str = "",
) -> list[AlertItem]:
    threshold = target.threshold if target.threshold is not None else 0.8
    request = _request_payload(payload)
    mode = str(request.get("mode", _resolve_mode(target))).strip().lower() or _resolve_mode(target)
    prediction_time = str(request.get("prediction_time", "")).strip()
    location = _request_location(request)
    lat = location.get("lat", _require_float_option(target, "lat"))
    lon = location.get("lon", _require_float_option(target, "lon"))
    site = _meaningful_site(site_hint or _request_site(request) or _to_string(payload.get("site")))
    sources = _normalize_sources(payload.get("sources"))
    source_signature = _source_signature(sources)
    source_summary = _source_summary(sources)
    celestial = _normalize_celestial(payload.get("celestial"))
    illumination = _payload_illumination(request) or _resolve_illumination(target)
    phenomenon_items = _phenomena_by_id(payload.get("phenomena"))
    selected_phenomena = _selected_phenomena(target, tuple(phenomenon_items))

    items: list[AlertItem] = []
    for phenomenon in selected_phenomena:
        entry = phenomenon_items.get(phenomenon)
        if entry is None:
            continue

        label = _entry_label(phenomenon, entry)
        primary_body = _primary_body_for_phenomenon(phenomenon, illumination)
        primary_altitude = _to_float(celestial.get(primary_body, {}).get("altitude"))
        current = entry.get("current") if isinstance(entry.get("current"), dict) else {}
        peak = entry.get("peak") if isinstance(entry.get("peak"), dict) else {}
        current_probability = _to_float(current.get("probability"))
        peak_probability = _to_peak_probability(entry)
        if peak_probability is None or peak_probability < threshold:
            continue

        confidence = _to_float(current.get("confidence"))
        reason = _to_string(current.get("reason"))
        peak_time = _to_string(peak.get("time"))
        timeline = _to_timeline(entry.get("timeline"))
        spatial_context = _to_spatial_context(current.get("spatial_context"))
        item_id = _build_item_id(
            phenomenon=phenomenon,
            mode=mode,
            source_signature=source_signature,
            peak_time=peak_time,
            probability=peak_probability,
            site=site,
            lat=lat,
            lon=lon,
        )
        message_parts = [
            f"{label}: peak probability {peak_probability:.3f}",
            f"Threshold: {threshold:.3f}",
        ]
        if site:
            message_parts.append(f"Site: {site}")
        message_parts.extend(
            [
                f"Mode: {mode}",
                f"Location: {lat:.4f}, {lon:.4f}",
            ]
        )
        if current_probability is not None:
            message_parts.append(f"Current probability: {current_probability:.3f}")
        if peak_time:
            message_parts.append(f"Peak time: {peak_time}")
        if confidence is not None:
            message_parts.append(f"Confidence: {confidence:.3f}")
        if primary_altitude is not None:
            message_parts.append(f"{primary_body.title()} altitude: {primary_altitude:.1f} deg")
        if reason:
            message_parts.append(f"Reason: {reason}")
        if prediction_time:
            message_parts.append(f"Prediction time: {prediction_time}")
        if source_summary:
            message_parts.append(f"Sources: {source_summary}")
        items.append(
            AlertItem(
                item_id=item_id,
                message="<br/>".join(message_parts),
                value=f"{peak_probability:.3f}",
                occurred_at=peak_time or (sources[0]["timestamp"] if sources else None),
                metadata={
                    "phenomenon": phenomenon,
                    "label": label,
                    "category": _to_string(entry.get("category")),
                    "mode": mode,
                    "illumination": illumination,
                    "site": site,
                    "lat": lat,
                    "lon": lon,
                    "probability": round(peak_probability, 3),
                    "current_probability": round(current_probability, 3) if current_probability is not None else None,
                    "peak_probability": round(peak_probability, 3),
                    "peak_time": peak_time,
                    "timeline": timeline,
                    "spatial_context": spatial_context,
                    "confidence": round(confidence, 3) if confidence is not None else None,
                    "celestial": celestial,
                    "primary_altitude": round(primary_altitude, 3) if primary_altitude is not None else None,
                    "reason": reason,
                    "prediction_time": prediction_time,
                    "sources": [dict(source) for source in sources],
                    "source_signature": source_signature,
                },
            )
        )
    return items


def _parse_payload(content: str) -> dict[str, object]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid atmospheric_optics JSON payload.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Atmospheric optics payload must be a JSON object.")
    return payload


def _prediction_payloads(payload: dict[str, object]) -> tuple[tuple[dict[str, object], str], ...]:
    locations = payload.get("locations")
    if not isinstance(locations, list):
        return ((payload, _to_string(payload.get("site"))),)

    predictions: list[tuple[dict[str, object], str]] = []
    for entry in locations:
        if not isinstance(entry, dict):
            continue
        site = _to_string(entry.get("site"))
        prediction = entry.get("prediction")
        if isinstance(prediction, dict):
            predictions.append((prediction, site))
        elif isinstance(entry.get("phenomena"), list) or isinstance(entry.get("request"), dict):
            predictions.append((entry, site))

    return tuple(predictions) or ((payload, _to_string(payload.get("site"))),)


def _request_payload(payload: dict[str, object]) -> dict[str, object]:
    request = payload.get("request")
    if isinstance(request, dict):
        return request
    return {}


def _request_location(request: dict[str, object]) -> dict[str, float]:
    location = request.get("location")
    if not isinstance(location, dict):
        return {}
    normalized: dict[str, float] = {}
    for key in ("lat", "lon"):
        try:
            normalized[key] = float(location[key])
        except (KeyError, TypeError, ValueError):
            continue
    return normalized


def _request_site(request: dict[str, object]) -> str:
    location = request.get("location")
    if not isinstance(location, dict):
        return ""
    return _to_string(location.get("site"))


def _resolve_locations(target: TargetConfig) -> tuple[dict[str, object], ...]:
    latitudes = _require_float_values(target, "lat")
    longitudes = _require_float_values(target, "lon")
    if len(latitudes) != len(longitudes):
        raise ValueError(
            "atmospheric_optics target options 'lat' and 'lon' must contain the same number of values."
        )

    site_values = _option_parts(target, "site")
    if not site_values:
        sites = tuple("NA" for _ in latitudes)
    elif len(site_values) != len(latitudes):
        raise ValueError(
            "atmospheric_optics target option 'site' must contain one value for each lat/lon pair."
        )
    else:
        sites = site_values

    return tuple(
        {
            "lat": latitudes[index],
            "lon": longitudes[index],
            "site": sites[index],
        }
        for index in range(len(latitudes))
    )


def _location_sites_configured(target: TargetConfig) -> bool:
    return bool(_option_parts(target, "site"))


def _option_parts(target: TargetConfig, key: str) -> tuple[str, ...]:
    value = target.options.get(key)
    if value is None:
        return ()
    raw_values = value if isinstance(value, (list, tuple)) else (value,)
    parts: list[str] = []
    for raw_value in raw_values:
        for part in str(raw_value).split(","):
            normalized = part.strip()
            if normalized:
                parts.append(normalized)
    return tuple(parts)


def _require_float_values(target: TargetConfig, key: str) -> tuple[float, ...]:
    values = _option_parts(target, key)
    if not values:
        raise ValueError(f"atmospheric_optics target option '{key}' must contain at least one numeric value.")

    parsed: list[float] = []
    for value in values:
        try:
            parsed.append(float(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"atmospheric_optics target option '{key}' must be numeric.") from exc
    return tuple(parsed)


def _join_csv(values) -> str:
    return ",".join(str(value) for value in values)


def _resolve_project_dir(target: TargetConfig) -> Path:
    project_dir = Path(option_str(target, "project_dir") or DEFAULT_PROJECT_DIR).expanduser()
    if not project_dir.is_dir():
        raise FileNotFoundError(f"atmospheric_optics project_dir does not exist: {project_dir}")
    return project_dir


def _resolve_mode(target: TargetConfig) -> str:
    mode = (option_str(target, "mode") or "observed").lower()
    if mode not in WEATHER_MODES:
        expected = ", ".join(sorted(WEATHER_MODES))
        raise ValueError(f"Unsupported atmospheric_optics mode '{mode}'. Expected one of: {expected}")
    return mode


def _resolve_illumination(target: TargetConfig) -> str:
    return _normalize_illumination(option_str(target, "illumination") or DEFAULT_ILLUMINATION)


def _payload_illumination(request: dict[str, object]) -> str:
    options = request.get("options")
    if not isinstance(options, dict):
        return ""
    value = options.get("illumination")
    if value is None:
        return ""
    return _normalize_illumination(str(value))


def _normalize_illumination(value: str) -> str:
    illuminations: list[str] = []
    invalid: list[str] = []
    for part in str(value).split(","):
        illumination = part.strip().lower()
        if not illumination:
            continue
        if illumination not in ILLUMINATION_MODES:
            invalid.append(illumination)
            continue
        if illumination not in illuminations:
            illuminations.append(illumination)
    if invalid:
        expected = ", ".join(sorted(ILLUMINATION_MODES) + [DEFAULT_ILLUMINATION])
        raise ValueError(
            f"Unsupported atmospheric_optics illumination '{value}'. Expected one of: {expected}"
        )
    if not illuminations:
        return DEFAULT_ILLUMINATION
    return ",".join(illuminations)


def _primary_body_for_phenomenon(phenomenon: str, illumination: str) -> str:
    illuminations = tuple(part for part in illumination.split(",") if part)
    if illuminations == ("lunar",):
        return "moon"
    if illuminations == ("solar",):
        return "sun"
    if phenomenon in LUNAR_PHENOMENA or phenomenon.startswith("lunar_"):
        return "moon"
    return "sun"


def _selected_phenomena(target: TargetConfig, available: tuple[str, ...]) -> tuple[str, ...]:
    configured = target.options.get("phenomena")
    if configured is None:
        return available
    if not isinstance(configured, (list, tuple)):
        raise ValueError("atmospheric_optics phenomena must be a list of names.")

    selected: list[str] = []
    invalid: list[str] = []
    for value in configured:
        name = str(value).strip().lower()
        if not name:
            continue
        if name not in available:
            invalid.append(name)
            continue
        if name not in selected:
            selected.append(name)
    if invalid:
        raise ValueError(
            "Unsupported atmospheric_optics phenomena: "
            + ", ".join(sorted(invalid))
        )
    if not selected:
        raise ValueError("atmospheric_optics phenomena cannot be empty when provided.")
    return tuple(selected)


def _require_float_option(target: TargetConfig, key: str) -> float:
    return _require_float_values(target, key)[0]


def _option_bool(target: TargetConfig, key: str, default: bool) -> bool:
    value = target.options.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"atmospheric_optics target option '{key}' must be boolean.")


def _option_csv(target: TargetConfig, key: str) -> str:
    value = target.options.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _normalize_sources(raw_sources: object) -> tuple[dict[str, str], ...]:
    if not isinstance(raw_sources, list):
        return ()

    normalized: list[dict[str, str]] = []
    for entry in raw_sources:
        if not isinstance(entry, dict):
            continue
        source_id = _to_string(entry.get("id") or entry.get("name"))
        label = _to_string(entry.get("label")) or _humanize_identifier(source_id)
        kind = _to_string(entry.get("kind"))
        timestamp = _to_string(entry.get("timestamp"))
        if not source_id and not timestamp:
            continue
        normalized.append(
            {
                "id": source_id,
                "label": label,
                "kind": kind,
                "timestamp": timestamp,
            }
        )
    return tuple(normalized)


def _normalize_celestial(raw_celestial: object) -> dict[str, dict[str, float]]:
    if not isinstance(raw_celestial, dict):
        return {}

    celestial: dict[str, dict[str, float]] = {}
    for body in ("sun", "moon"):
        entry = raw_celestial.get(body)
        if not isinstance(entry, dict):
            continue
        altitude = _to_float(entry.get("altitude"))
        if altitude is None:
            continue
        celestial[body] = {"altitude": altitude}
    return celestial


def _source_signature(sources: tuple[dict[str, str], ...]) -> str:
    if not sources:
        return ""
    return "|".join(
        f"{source['id']}@{source['timestamp']}".strip("@")
        for source in sources
    )


def _source_summary(sources: tuple[dict[str, str], ...]) -> str:
    return ", ".join(
        " ".join(part for part in (source["label"], source["timestamp"]) if part)
        for source in sources
    )


def _build_item_id(
    phenomenon: str,
    mode: str,
    source_signature: str,
    peak_time: str,
    probability: float,
    site: str = "",
    lat: float | None = None,
    lon: float | None = None,
) -> str:
    suffix = source_signature or peak_time or f"probability@{probability:.3f}"
    location_signature = _location_signature(site, lat, lon)
    if location_signature:
        suffix = f"{location_signature}:{suffix}"
    return f"{phenomenon}:{mode}:{suffix}"


def _location_signature(site: str, lat: float | None, lon: float | None) -> str:
    del lat, lon
    if site:
        return _slug(site)
    return ""


def _meaningful_site(site: str) -> str:
    normalized = _to_string(site)
    if normalized.upper() == "NA":
        return ""
    return normalized


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "site"


def _phenomena_by_id(raw_phenomena: object) -> dict[str, dict[str, object]]:
    if not isinstance(raw_phenomena, list):
        return {}

    phenomena: dict[str, dict[str, object]] = {}
    for entry in raw_phenomena:
        if not isinstance(entry, dict):
            continue
        phenomenon_id = _to_string(entry.get("id")).lower()
        if not phenomenon_id:
            continue
        phenomena[phenomenon_id] = entry
    return phenomena


def _entry_label(phenomenon: str, entry: dict[str, object]) -> str:
    label = _to_string(entry.get("label"))
    if label:
        return label
    return _humanize_identifier(phenomenon)


def _to_peak_probability(entry: dict[str, object]) -> float | None:
    peak = entry.get("peak")
    if isinstance(peak, dict):
        value = _to_float(peak.get("probability"))
        if value is not None:
            return value

    timeline = _to_timeline(entry.get("timeline"))
    if timeline:
        return max(timeline.values())

    current = entry.get("current")
    if isinstance(current, dict):
        return _to_float(current.get("probability"))
    return None


def _to_timeline(value: object) -> dict[str, float]:
    if not isinstance(value, list):
        return {}

    timeline: dict[str, float] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        label = _to_string(item.get("label"))
        probability = _to_float(item.get("probability"))
        if not label or probability is None:
            continue
        timeline[label] = probability
    return timeline


def _to_spatial_context(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}

    spatial_context: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, str):
            spatial_context[str(key)] = item
            continue
        try:
            spatial_context[str(key)] = float(item)
        except (TypeError, ValueError):
            continue
    return spatial_context


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _humanize_identifier(value: str) -> str:
    if not value:
        return ""
    return value.replace("_", " ").replace("-", " ").title()


PROVIDER = AtmosphericOpticsProvider()


if __name__ == "__main__":
    raise SystemExit(main())

"""Atmospheric optics provider backed by the sibling predictor repo."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from alert.models import AlertItem, SourceConfig, TargetConfig
from alert.providers._helpers import option_str
from alert.providers.base import AlertProvider

WEATHER_MODES = {"forecast", "observed"}
DEFAULT_PROJECT_DIR = Path(__file__).resolve().parents[3] / "atmospheric_optics"


class AtmosphericOpticsProvider(AlertProvider):
    name = "atmospheric_optics"
    default_email_title = "Atmospheric Optics Alert"

    def fetch_content(self, target: TargetConfig, http_client: object) -> str:
        del http_client

        lat = _require_float_option(target, "lat")
        lon = _require_float_option(target, "lon")
        mode = _resolve_mode(target)
        project_dir = _resolve_project_dir(target)
        cli_path = project_dir / "cli" / "main.py"
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
        command = [
            python_path,
            str(cli_path),
            "--lat",
            str(lat),
            "--lon",
            str(lon),
            "--mode",
            mode,
        ]
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
        threshold = target.threshold if target.threshold is not None else 0.8
        request = _request_payload(payload)
        mode = str(request.get("mode", _resolve_mode(target))).strip().lower() or _resolve_mode(target)
        prediction_time = str(request.get("prediction_time", "")).strip()
        location = _request_location(request)
        lat = location.get("lat", _require_float_option(target, "lat"))
        lon = location.get("lon", _require_float_option(target, "lon"))
        sources = _normalize_sources(payload.get("sources"))
        source_signature = _source_signature(sources)
        source_summary = _source_summary(sources)
        phenomenon_items = _phenomena_by_id(payload.get("phenomena"))
        selected_phenomena = _selected_phenomena(target, tuple(phenomenon_items))

        items: list[AlertItem] = []
        for phenomenon in selected_phenomena:
            entry = phenomenon_items.get(phenomenon)
            if entry is None:
                continue

            label = _entry_label(phenomenon, entry)
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
            )
            message_parts = [
                f"{label}: peak probability {peak_probability:.3f}",
                f"Threshold: {threshold:.3f}",
                f"Mode: {mode}",
                f"Location: {lat:.4f}, {lon:.4f}",
            ]
            if current_probability is not None:
                message_parts.append(f"Current probability: {current_probability:.3f}")
            if peak_time:
                message_parts.append(f"Peak time: {peak_time}")
            if confidence is not None:
                message_parts.append(f"Confidence: {confidence:.3f}")
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
                        "lat": lat,
                        "lon": lon,
                        "probability": round(peak_probability, 3),
                        "current_probability": round(current_probability, 3) if current_probability is not None else None,
                        "peak_probability": round(peak_probability, 3),
                        "peak_time": peak_time,
                        "timeline": timeline,
                        "spatial_context": spatial_context,
                        "confidence": round(confidence, 3) if confidence is not None else None,
                        "reason": reason,
                        "prediction_time": prediction_time,
                        "sources": [dict(source) for source in sources],
                        "source_signature": source_signature,
                    },
                )
            )
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


def _parse_payload(content: str) -> dict[str, object]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid atmospheric_optics JSON payload.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Atmospheric optics payload must be a JSON object.")
    return payload


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
    value = target.options.get(key)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"atmospheric_optics target option '{key}' must be numeric.") from exc


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
) -> str:
    suffix = source_signature or peak_time or f"probability@{probability:.3f}"
    return f"{phenomenon}:{mode}:{suffix}"


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

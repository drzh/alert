"""Atmospheric optics provider backed by the sibling predictor repo."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from alert.models import AlertItem, SourceConfig, TargetConfig
from alert.providers._helpers import option_str
from alert.providers.base import AlertProvider

SUPPORTED_PHENOMENA = ("halo", "parhelia", "cza", "rainbow")
PHENOMENON_LABELS = {
    "halo": "Halo",
    "parhelia": "Parhelia",
    "cza": "Circumzenithal Arc",
    "rainbow": "Rainbow",
}
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
        mode = _resolve_mode(target)
        lat = _require_float_option(target, "lat")
        lon = _require_float_option(target, "lon")
        sources = _normalize_sources(payload.get("sources"))
        source_signature = _source_signature(sources)
        source_summary = _source_summary(sources)

        items: list[AlertItem] = []
        for phenomenon in _selected_phenomena(target):
            probability = _to_float(payload.get(phenomenon))
            if probability is None or probability < threshold:
                continue

            label = PHENOMENON_LABELS[phenomenon]
            item_id = _build_item_id(
                phenomenon=phenomenon,
                mode=mode,
                source_signature=source_signature,
                probability=probability,
            )
            message_parts = [
                f"{label}: probability {probability:.3f}",
                f"Threshold: {threshold:.3f}",
                f"Mode: {mode}",
                f"Location: {lat:.4f}, {lon:.4f}",
            ]
            if source_summary:
                message_parts.append(f"Sources: {source_summary}")
            items.append(
                AlertItem(
                    item_id=item_id,
                    message="<br/>".join(message_parts),
                    value=f"{probability:.3f}",
                    occurred_at=sources[0]["timestamp"] if sources else None,
                    metadata={
                        "phenomenon": phenomenon,
                        "mode": mode,
                        "lat": lat,
                        "lon": lon,
                        "probability": round(probability, 3),
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
                phenomenon = str(alert.metadata.get("phenomenon", "")).strip().lower()
                label = PHENOMENON_LABELS.get(phenomenon)
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


def _selected_phenomena(target: TargetConfig) -> tuple[str, ...]:
    configured = target.options.get("phenomena")
    if configured is None:
        return SUPPORTED_PHENOMENA
    if not isinstance(configured, (list, tuple)):
        raise ValueError("atmospheric_optics phenomena must be a list of names.")

    selected: list[str] = []
    invalid: list[str] = []
    for value in configured:
        name = str(value).strip().lower()
        if not name:
            continue
        if name not in SUPPORTED_PHENOMENA:
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


def _normalize_sources(raw_sources: object) -> tuple[dict[str, str], ...]:
    if not isinstance(raw_sources, list):
        return ()

    normalized: list[dict[str, str]] = []
    for entry in raw_sources:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        timestamp = str(entry.get("timestamp", "")).strip()
        if not name and not timestamp:
            continue
        normalized.append({"name": name, "timestamp": timestamp})
    return tuple(normalized)


def _source_signature(sources: tuple[dict[str, str], ...]) -> str:
    if not sources:
        return ""
    return "|".join(
        f"{source['name']}@{source['timestamp']}".strip("@")
        for source in sources
    )


def _source_summary(sources: tuple[dict[str, str], ...]) -> str:
    return ", ".join(
        " ".join(part for part in (source["name"], source["timestamp"]) if part)
        for source in sources
    )


def _build_item_id(
    phenomenon: str,
    mode: str,
    source_signature: str,
    probability: float,
) -> str:
    suffix = source_signature or f"probability@{probability:.3f}"
    return f"{phenomenon}:{mode}:{suffix}"


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


PROVIDER = AtmosphericOpticsProvider()

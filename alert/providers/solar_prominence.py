"""Solar prominence record comparison provider."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse
from urllib.request import url2pathname

from alert.config import load_config
from alert.models import AlertItem, Attachment, StoredAlert, TargetConfig
from alert.providers._helpers import option_float, option_int, option_str, parse_tab_mapping, read_tab_file, write_tab_file
from alert.providers.base import AlertProvider

DEFAULT_METRICS_CALCULATOR = Path(__file__).resolve().parents[3] / "hobby" / "astro" / "calc_solar_prominence_area.py"


class SolarProminenceProvider(AlertProvider):
    name = "solar_prominence"
    default_email_title = "Solar Prominence Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        values = parse_tab_mapping(content)
        current_time = values.get("current_time")
        if not current_time:
            return []

        attachments: tuple[Attachment, ...] = ()
        attachment_path = option_str(target, "attachment_path")
        if attachment_path and Path(attachment_path).is_file():
            attachments = (Attachment(path=attachment_path),)

        return [
            AlertItem(
                item_id=current_time,
                message=(
                    f"Solar prominence at {escape(current_time)}<br/>"
                    "<table>"
                    "<tr><th>Metric</th><th>Value</th></tr>"
                    f"<tr><td>Max intensity</td><td>{escape(values.get('intensity_max', '0'))}</td></tr>"
                    f"<tr><td>Max distance</td><td>{escape(values.get('prominence_max_distance_pixels', '0'))} pixels</td></tr>"
                    f"<tr><td>Area</td><td>{escape(values.get('prominence_area_pixels', '0'))} pixels</td></tr>"
                    "</table>"
                ),
                occurred_at=current_time,
                metadata=values,
                attachments=attachments,
            )
        ]

    def should_alert(
        self,
        history: Sequence[StoredAlert],
        item: AlertItem,
        target: TargetConfig,
    ) -> bool:
        current_time = _parse_datetime(item.occurred_at)
        if current_time is None:
            return False

        previous = _load_previous_record(target, history, current_time)
        previous_time = _parse_datetime(previous.get("current_time"))
        trigger_minutes = option_int(target, "time_threshold_minutes", 10)
        if previous_time is not None and (current_time - previous_time).total_seconds() <= trigger_minutes * 60:
            return False

        current_distance = _metadata_float(item.metadata, "prominence_max_distance_pixels")
        current_area = _metadata_float(item.metadata, "prominence_area_pixels")
        current_intensity = _metadata_float(item.metadata, "intensity_max")
        previous_distance = _mapping_float(previous, "prominence_max_distance_pixels")
        previous_area = _mapping_float(previous, "prominence_area_pixels")
        previous_intensity = _mapping_float(previous, "intensity_max")
        distance_threshold = option_float(target, "distance_threshold", 20.0)
        area_threshold = option_float(target, "area_threshold", 2000.0)
        intensity_threshold = option_float(target, "intensity_threshold", 1000.0)

        return (
            (current_distance > distance_threshold and current_distance > previous_distance)
            or (current_area > area_threshold and current_area > previous_area)
            or (current_intensity > intensity_threshold and current_intensity > previous_intensity)
        )

    def after_target(
        self,
        target: TargetConfig,
        items: Sequence[AlertItem],
        pending: Sequence[AlertItem],
        content: str,
        *,
        persist: bool,
        notification_sent: bool,
    ) -> None:
        state_file = option_str(target, "state_file")
        if not persist or not state_file or not items:
            return

        values = parse_tab_mapping(content)
        current_time = _parse_datetime(values.get("current_time"))
        previous = read_tab_file(state_file)
        previous_time = _parse_datetime(previous.get("current_time"))

        if pending and notification_sent:
            write_tab_file(state_file, values)
            return

        if current_time is None or previous_time is None:
            return

        remove_minutes = option_int(target, "remove_threshold_minutes", 60)
        if (current_time - previous_time).total_seconds() > remove_minutes * 60:
            state_path = Path(state_file)
            if state_path.exists():
                state_path.unlink()


def _load_previous_record(
    target: TargetConfig,
    history: Sequence[StoredAlert],
    current_time: datetime,
) -> dict[str, str]:
    state_file = option_str(target, "state_file")
    previous = read_tab_file(state_file)
    if previous:
        return previous

    if history:
        latest = history[0]
        latest_time = _parse_datetime(latest.metadata.get("current_time") or latest.occurred_at)
        remove_minutes = option_int(target, "remove_threshold_minutes", 60)
        if latest_time is not None and (current_time - latest_time).total_seconds() > remove_minutes * 60:
            return {}
        return {
            key: str(value)
            for key, value in latest.metadata.items()
        }
    return {}


def build_metrics_command(
    target: TargetConfig,
    fits_file: Path,
    *,
    output_path: Path | None = None,
    plot_path: Path | None = None,
) -> list[str]:
    calculator_path = Path(option_str(target, "metrics_calculator_path") or DEFAULT_METRICS_CALCULATOR)
    if not calculator_path.is_file():
        raise FileNotFoundError(f"solar prominence metrics calculator not found: {calculator_path}")

    output = output_path or _target_file_path(target)
    configured_plot_path = option_str(target, "attachment_path")
    plot = plot_path or (Path(configured_plot_path) if configured_plot_path else None)
    command = [
        option_str(target, "metrics_python_path") or sys.executable,
        str(calculator_path),
        "-e",
        str(option_int(target, "metrics_extend_pixels", 10)),
        "-c",
        str(option_int(target, "metrics_intensity_cutoff", 10)),
        "-m",
        str(option_int(target, "metrics_minimal_pixels", 10)),
        "-w",
        str(option_int(target, "metrics_plot_width", 3)),
        "-h",
        str(option_int(target, "metrics_plot_height", 3)),
        "-i",
        str(fits_file),
        "-o",
        str(output),
    ]
    if plot is not None:
        command.extend(["-p", str(plot)])
    return command


def generate_metrics(
    target: TargetConfig,
    fits_file: Path,
    *,
    output_path: Path | None = None,
    plot_path: Path | None = None,
) -> None:
    command = build_metrics_command(
        target,
        fits_file,
        output_path=output_path,
        plot_path=plot_path,
    )
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=option_float(target, "metrics_timeout_seconds", 300.0),
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"solar prominence metrics command failed: {detail}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate solar prominence metrics from the configured target.")
    parser.add_argument("--config", required=True, help="Alert TOML config path.")
    parser.add_argument("--source", default="solar_prominence", help="Source name to use.")
    parser.add_argument("--target-name", default="", help="Optional target name. Defaults to the first target in the source.")
    parser.add_argument("--fits-file", required=True, type=Path, help="Input FITS file.")
    parser.add_argument("--output", type=Path, help="Optional metrics output file override. Defaults to the target URL.")
    parser.add_argument("--plot", type=Path, help="Optional plot output override. Defaults to attachment_path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    source = config.get_source(args.source)
    target = _select_target(source.targets, args.target_name.strip())
    generate_metrics(
        target,
        args.fits_file.expanduser().resolve(),
        output_path=args.output.expanduser().resolve() if args.output else None,
        plot_path=args.plot.expanduser().resolve() if args.plot else None,
    )
    return 0


def _select_target(targets: Sequence[TargetConfig], target_name: str) -> TargetConfig:
    if target_name:
        for target in targets:
            if (target.name or "") == target_name:
                return target
        raise ValueError(f"Target not found: {target_name}")
    return targets[0]


def _target_file_path(target: TargetConfig) -> Path:
    parsed = urlparse(target.url)
    if parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost"):
            raise ValueError(f"solar prominence target must be a local file URL: {target.url}")
        return Path(url2pathname(parsed.path))
    if parsed.scheme:
        raise ValueError(f"solar prominence target must be a local file URL: {target.url}")
    return Path(target.url).expanduser().resolve()


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _metadata_float(metadata: object, key: str) -> float:
    if isinstance(metadata, dict):
        return _mapping_float(metadata, key)
    return 0.0


def _mapping_float(mapping: object, key: str) -> float:
    if isinstance(mapping, dict):
        try:
            return float(mapping.get(key, 0))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


PROVIDER = SolarProminenceProvider()


if __name__ == "__main__":
    raise SystemExit(main())

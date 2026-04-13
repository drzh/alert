"""NOAA SWPC 3-day aurora forecast provider."""

from __future__ import annotations

from html import escape
from pathlib import Path
import re
from typing import Mapping, Sequence

from alert.models import AlertItem, SourceConfig, StoredAlert, TargetConfig
from alert.providers._helpers import option_str, read_tab_file, write_tab_file
from alert.providers.base import AlertProvider

STATE_ORDER = ("threehr_max", "day1_max", "day2_max", "day3_max")
ROW_LABELS = (
    "00-03UT",
    "03-06UT",
    "06-09UT",
    "09-12UT",
    "12-15UT",
    "15-18UT",
    "18-21UT",
    "21-00UT",
)
THREE_HOUR_PATTERN = re.compile(r"The greatest expected 3 hr Kp for [^\n]+ is (\d+(?:\.\d+)?)")
KP_VALUE_PATTERN = re.compile(r"\d+(?:\.\d+)?")


class AuroraProvider(AlertProvider):
    name = "aurora"
    default_email_title = "Aurora Alert"

    def parse_items(self, target: TargetConfig, content: str) -> list[AlertItem]:
        three_hour_match = THREE_HOUR_PATTERN.search(content)
        three_hour_max = float(three_hour_match.group(1)) if three_hour_match else None
        table_lines, table_values = _extract_table(content)
        if three_hour_max is None and not table_values:
            return []

        table_html = f"<pre>{escape(chr(10).join(table_lines))}</pre>" if table_lines else ""
        day_maxima = _compute_day_maxima(table_values)
        raw_values = {
            "threehr_max": float(three_hour_max or 0),
            "day1_max": float(day_maxima[0]),
            "day2_max": float(day_maxima[1]),
            "day3_max": float(day_maxima[2]),
        }

        labels = {
            "threehr_max": "Aurora Kp in next three hours",
            "day1_max": "Aurora Kp in one day",
            "day2_max": "Aurora Kp in two days",
            "day3_max": "Aurora Kp in three days",
        }
        return [
            AlertItem(
                item_id=f"{stable_id}:{value:g}",
                message=f"{labels[stable_id]} = {value:g}<br/>{table_html}",
                value=f"{value:g}",
                metadata={
                    "stable_id": stable_id,
                    "table": "\n".join(table_lines),
                    "summary": f"{labels[stable_id]} = {value:g}",
                },
            )
            for stable_id, value in raw_values.items()
        ]

    def should_alert(
        self,
        history: Sequence[StoredAlert],
        item: AlertItem,
        target: TargetConfig,
    ) -> bool:
        threshold = target.threshold if target.threshold is not None else 7.0
        current = _to_float(item.value)
        if current is None or current < threshold:
            return False

        stable_id = str(item.metadata.get("stable_id", item.item_id))
        previous_state = read_tab_file(option_str(target, "state_file"))
        if stable_id in previous_state:
            previous = _to_float(previous_state[stable_id])
            return previous is None or current > previous

        for record in history:
            if record.metadata.get("stable_id", record.item_id) == stable_id:
                previous = _to_float(record.value)
                return previous is None or current > previous
        return True

    def build_subject(
        self,
        source: SourceConfig,
        alerts_by_target: Mapping[str, Sequence[AlertItem]],
    ) -> str:
        summaries = [
            str(alert.metadata.get("summary", alert.value or alert.item_id))
            for alerts in alerts_by_target.values()
            for alert in alerts
        ]
        if not summaries:
            return source.resolved_email_title(self.default_email_title)
        return f"{source.resolved_email_title(self.default_email_title)}: " + "; ".join(summaries)

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
        if not persist:
            return

        state_file = option_str(target, "state_file")
        if state_file:
            state = {
                str(item.metadata.get("stable_id", item.item_id)): item.value or "0"
                for item in items
            }
            write_tab_file(state_file, state, order=STATE_ORDER)

        table_output_file = option_str(target, "table_output_file")
        if table_output_file:
            table_lines, _ = _extract_table(content)
            if table_lines:
                table_output_path = Path(table_output_file)
                table_output_path.parent.mkdir(parents=True, exist_ok=True)
                table_output_path.write_text("\n".join(table_lines) + "\n", encoding="utf-8")


def _extract_table(content: str) -> tuple[list[str], list[tuple[float, float, float]]]:
    lines = content.splitlines()
    table_lines: list[str] = []
    table_values: list[tuple[float, float, float]] = []
    start_index: int | None = None

    for index, line in enumerate(lines):
        if line.strip().startswith("00-03UT"):
            start_index = max(index - 1, 0)
            break

    if start_index is None:
        return table_lines, table_values

    for line in lines[start_index:]:
        stripped = line.strip()
        if not stripped:
            if table_lines:
                break
            continue

        if not table_lines:
            table_lines.append(line.rstrip())
            continue

        row_label = next((label for label in ROW_LABELS if stripped.startswith(label)), None)
        if row_label is not None:
            table_lines.append(line.rstrip())
            row_text = stripped[len(row_label):]
            row_text = re.sub(r"\([^)]*\)", "", row_text)
            values = [float(value) for value in KP_VALUE_PATTERN.findall(row_text)]
            if len(values) >= 3:
                table_values.append((values[0], values[1], values[2]))
            if stripped.startswith("21-00UT"):
                break
            continue

        if table_values:
            break

    return [line.strip() for line in table_lines], table_values


def _compute_day_maxima(table_values: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    if not table_values:
        return (0.0, 0.0, 0.0)
    columns = list(zip(*table_values))
    return tuple(max(column) for column in columns)


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


PROVIDER = AuroraProvider()

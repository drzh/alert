"""Shared helper functions for alert providers."""

from __future__ import annotations

from html import escape
from pathlib import Path
import re
from typing import Mapping

from alert.models import TargetConfig


def option_float(target: TargetConfig, key: str, default: float) -> float:
    value = target.options.get(key, default)
    return float(value)


def option_int(target: TargetConfig, key: str, default: int) -> int:
    value = target.options.get(key, default)
    return int(value)


def option_str(target: TargetConfig, key: str) -> str | None:
    value = target.options.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_tab_mapping(content: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        mapping[parts[0].strip()] = parts[1].strip()
    return mapping


def read_tab_file(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    return parse_tab_mapping(file_path.read_text(encoding="utf-8"))


def write_tab_file(path: str, mapping: Mapping[str, object], order: tuple[str, ...] | None = None) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    keys = list(order or ())
    keys.extend(key for key in mapping if key not in keys)

    lines = [f"{key}\t{mapping[key]}" for key in keys if key in mapping]
    file_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def load_blacklist_patterns(target: TargetConfig) -> tuple[str, ...]:
    patterns: list[str] = []
    configured = target.options.get("blacklist", ())
    if isinstance(configured, (list, tuple)):
        patterns.extend(str(value) for value in configured if str(value).strip())

    blacklist_file = option_str(target, "blacklist_file")
    if blacklist_file:
        file_path = Path(blacklist_file)
        if file_path.is_file():
            for raw_line in file_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    return tuple(patterns)


def is_blacklisted(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def html_link(url: str, label: str | None = None) -> str:
    safe_url = escape(url, quote=True)
    safe_label = escape(label or url)
    return f'<a href="{safe_url}">{safe_label}</a>'

"""Configuration loading for the alert system."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import tomllib

from .models import AppConfig, SmtpConfig, SourceConfig, TargetConfig

KNOWN_SOURCE_KEYS = {"name", "provider", "db_file", "email_title", "targets", "keep_records"}
KNOWN_TARGET_KEYS = {"url", "threshold", "name", "timeout_seconds"}
PATH_OPTION_SUFFIXES = ("_file", "_path", "_dir")
PATH_LIST_OPTION_SUFFIXES = ("_files", "_paths", "_dirs")


def load_config(path: str | Path) -> AppConfig:
    """Load a TOML configuration file."""

    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file does not exist: {config_path}")

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    smtp_config = _load_smtp_config(raw.get("smtp"))
    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("Config must include at least one [[sources]] entry.")

    sources = tuple(_load_source_config(config_path.parent, entry) for entry in raw_sources)
    return AppConfig(sources=sources, smtp=smtp_config)


def _load_smtp_config(raw_smtp: object) -> SmtpConfig | None:
    if raw_smtp is None:
        return None
    if not isinstance(raw_smtp, dict):
        raise ValueError("[smtp] must be a table.")

    recipients = raw_smtp.get("recipients")
    if not isinstance(recipients, list) or not recipients:
        raise ValueError("[smtp].recipients must be a non-empty array.")

    return SmtpConfig(
        host=_require_string(raw_smtp, "host", context="[smtp]"),
        port=int(raw_smtp.get("port", 587)),
        username=_require_string(raw_smtp, "username", context="[smtp]"),
        password_env=_require_string(raw_smtp, "password_env", context="[smtp]"),
        sender=_require_string(raw_smtp, "sender", context="[smtp]"),
        recipients=tuple(_require_string_value(value, context="[smtp].recipients") for value in recipients),
        starttls=bool(raw_smtp.get("starttls", True)),
    )


def _load_source_config(config_dir: Path, raw_source: object) -> SourceConfig:
    if not isinstance(raw_source, dict):
        raise ValueError("Each [[sources]] entry must be a table.")

    name = _require_string(raw_source, "name", context="[[sources]]")
    provider = _require_string(raw_source, "provider", context=f"[[sources]] {name}")
    raw_targets = raw_source.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError(f"Source '{name}' must include at least one [[sources.targets]] entry.")

    db_file = raw_source.get("db_file", f"{name}.db")
    db_path = (config_dir / _require_string_value(db_file, context=f"source '{name}' db_file")).resolve()
    email_title = raw_source.get("email_title")
    keep_records = int(raw_source.get("keep_records", 1000))
    if keep_records < 0:
        raise ValueError(f"Source '{name}' keep_records must be non-negative.")

    options = _normalize_extra_mapping(config_dir, raw_source, KNOWN_SOURCE_KEYS)
    targets = tuple(_load_target_config(config_dir, entry, source_name=name) for entry in raw_targets)

    return SourceConfig(
        name=name,
        provider=provider,
        db_file=str(db_path),
        email_title=_optional_string_value(email_title),
        targets=targets,
        keep_records=keep_records,
        options=options,
    )


def _load_target_config(config_dir: Path, raw_target: object, source_name: str) -> TargetConfig:
    if not isinstance(raw_target, dict):
        raise ValueError(f"Targets for source '{source_name}' must be tables.")

    threshold = raw_target.get("threshold")
    if threshold is not None:
        threshold = float(threshold)

    timeout_seconds = float(raw_target.get("timeout_seconds", 30.0))
    if timeout_seconds <= 0.0:
        raise ValueError(f"Target timeout_seconds for source '{source_name}' must be positive.")

    options = _normalize_extra_mapping(config_dir, raw_target, KNOWN_TARGET_KEYS)
    url = _normalize_target_url(
        config_dir,
        _require_string(raw_target, "url", context=f"source '{source_name}' target"),
    )

    return TargetConfig(
        url=url,
        threshold=threshold,
        name=_optional_string_value(raw_target.get("name")),
        timeout_seconds=timeout_seconds,
        options=options,
    )


def _require_string(mapping: dict[str, object], key: str, context: str) -> str:
    if key not in mapping:
        raise ValueError(f"Missing required key {key!r} in {context}.")
    return _require_string_value(mapping[key], context=f"{context}.{key}")


def _require_string_value(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string.")
    return value.strip()


def _optional_string_value(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Optional string value must be a string when provided.")
    stripped = value.strip()
    return stripped or None


def _normalize_extra_mapping(
    config_dir: Path,
    mapping: dict[str, Any],
    known_keys: set[str],
) -> dict[str, Any]:
    return {
        key: _normalize_extra_value(config_dir, key, value)
        for key, value in mapping.items()
        if key not in known_keys
    }


def _normalize_extra_value(config_dir: Path, key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {
            nested_key: _normalize_extra_value(config_dir, nested_key, nested_value)
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list) and key.endswith(PATH_LIST_OPTION_SUFFIXES):
        return [
            str((config_dir / item).resolve()) if isinstance(item, str) else item
            for item in value
        ]
    if isinstance(value, str) and key.endswith(PATH_OPTION_SUFFIXES):
        return str((config_dir / value).resolve())
    return value


def _normalize_target_url(config_dir: Path, url: str) -> str:
    if "://" in url:
        return url
    if url.startswith(("/", "./", "../")):
        return Path(url if url.startswith("/") else config_dir / url).resolve().as_uri()
    return url

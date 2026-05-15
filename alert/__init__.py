"""Alert package."""

from __future__ import annotations


def __getattr__(name: str):
    if name == "AlertRunner":
        from alert.app import AlertRunner

        return AlertRunner
    if name == "load_config":
        from alert.config import load_config

        return load_config
    raise AttributeError(f"module 'alert' has no attribute {name!r}")

__all__ = ["AlertRunner", "load_config"]

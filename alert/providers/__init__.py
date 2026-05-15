"""Built-in alert providers."""

from __future__ import annotations

from importlib import import_module

from alert.providers.base import AlertProvider

PROVIDER_MODULES = (
    "ariss",
    "atmospheric_optics",
    "aurora",
    "aurora_gfz",
    "bz",
    "cc",
    "cl",
    "ha_comet",
    "rocketlaunch",
    "sd",
    "solar_prominence",
    "solarspot",
    "spaceweather_com",
    "spaceweather_gov",
    "spaceweather_gov_alerts",
)


def load_builtin_providers() -> tuple[AlertProvider, ...]:
    providers: list[AlertProvider] = []
    for module_name in PROVIDER_MODULES:
        module = import_module(f"{__name__}.{module_name}")
        providers.append(module.PROVIDER)
    return tuple(providers)


__all__ = ["PROVIDER_MODULES", "load_builtin_providers"]

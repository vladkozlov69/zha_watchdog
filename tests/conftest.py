# Copyright (c) 2026 Vladimir Kozlov <vkozloff@gmail.com>
# SPDX-License-Identifier: MIT

"""Test setup for the zha_watchdog custom integration."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

import pytest


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "zha_watchdog"


def _load_package(name: str, path: Path, search_locations: list[str] | None = None):
    spec = spec_from_file_location(
        name,
        path,
        submodule_search_locations=search_locations,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load package {name} from {path}")
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Ensure "zha_watchdog" is importable as a package.
if PACKAGE_NAME not in sys.modules:
    _load_package(PACKAGE_NAME, INTEGRATION_ROOT / "__init__.py", [str(INTEGRATION_ROOT)])
else:
    # Make sure it points to this checkout when reused.
    module = sys.modules[PACKAGE_NAME]
    module.__path__ = [str(INTEGRATION_ROOT)]  # type: ignore[attr-defined]

# Also expose as custom_components.zha_watchdog for imports that use that namespace.
if "custom_components" not in sys.modules:
    cc = types.ModuleType("custom_components")
    cc.__path__ = [str(INTEGRATION_ROOT.parent)]  # type: ignore[attr-defined]
    sys.modules["custom_components"] = cc

sys.modules[f"custom_components.{PACKAGE_NAME}"] = sys.modules[PACKAGE_NAME]


@pytest.fixture(autouse=True)
def _reset_zha_watchdog_domain_data(hass):
    """Ensure a clean domain data container for each test."""
    hass.data.setdefault(PACKAGE_NAME, {})
    hass.data[PACKAGE_NAME].clear()
    yield
    hass.data.get(PACKAGE_NAME, {}).clear()

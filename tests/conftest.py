"""Load the integration's pure-Python modules without importing Home Assistant."""

from __future__ import annotations

import sys
import types
from pathlib import Path

PKG = "custom_components.vanmoof_sa5"
ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "vanmoof_sa5"


def _stub_package() -> None:
    if PKG in sys.modules:
        return
    parent = types.ModuleType("custom_components")
    parent.__path__ = [str(ROOT.parent)]
    sys.modules["custom_components"] = parent
    package = types.ModuleType(PKG)
    package.__path__ = [str(ROOT)]
    sys.modules[PKG] = package


_stub_package()

"""Framework-neutral registry for optional dynamically loaded AI features."""
from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any

from services.runtime_config import BASE_DIR

logger = logging.getLogger("revelaai.features")
FEATURES_DIR = BASE_DIR / "features"


def load_features() -> dict[str, Any]:
    """Load optional feature classes without depending on Flask request/app state."""
    features: dict[str, Any] = {}
    if not FEATURES_DIR.is_dir():
        return features

    for path in FEATURES_DIR.iterdir():
        if not path.is_file() or path.suffix != ".py":
            continue
        if path.name in {"loader.py", "__init__.py"}:
            continue

        module_name = f"features.{path.stem}"
        try:
            module = importlib.import_module(module_name)
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if obj.__module__ == module_name:
                    features[name.lower()] = obj()
        except Exception as exc:
            logger.warning(
                "Optional feature failed to load | feature=%s | error_type=%s",
                path.name,
                type(exc).__name__,
            )
    return features


FEATURES = load_features()

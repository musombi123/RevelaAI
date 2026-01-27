import os
import importlib
import inspect

FEATURES_PATH = "features"


def load_features():
    features = {}

    for file in os.listdir(FEATURES_PATH):
        if not file.endswith(".py"):
            continue
        if file in ("loader.py", "__init__.py"):
            continue

        module_name = f"{FEATURES_PATH}.{file[:-3]}"
        module = importlib.import_module(module_name)

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ == module_name:
                features[name.lower()] = obj()

    return features

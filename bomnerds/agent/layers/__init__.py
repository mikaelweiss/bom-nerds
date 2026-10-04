"""Every job layer, in build order. Each module here lists its layers in LAYERS."""

import importlib
import pkgutil

from ..layer import Layer


def discover() -> dict[str, Layer]:
    found = []
    for module in pkgutil.iter_modules(__path__):
        found += importlib.import_module(f"{__name__}.{module.name}").LAYERS
    return {layer.name: layer for layer in sorted(found, key=lambda layer: (layer.step, layer.name))}


LAYERS = discover()

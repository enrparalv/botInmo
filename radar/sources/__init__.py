from .base import Source
from .fotocasa import Fotocasa
from .pisos import Pisos
from .habitaclia import Habitaclia

REGISTRY = {c.name: c for c in (Fotocasa, Pisos, Habitaclia)}

__all__ = ["Source", "Fotocasa", "Pisos", "Habitaclia", "REGISTRY"]

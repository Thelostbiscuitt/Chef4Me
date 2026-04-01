"""Ingredient name normalization utilities."""
import json
from pathlib import Path

ALIASES_PATH = Path(__file__).parent.parent / "data" / "ingredient_aliases.json"

# Lazy-loaded alias map
_aliases_cache: dict[str, str] = {}


def _load_aliases() -> dict[str, str]:
    global _aliases_cache
    if not _aliases_cache and ALIASES_PATH.exists():
        with open(ALIASES_PATH) as f:
            _aliases_cache = json.load(f)
    return _aliases_cache


def normalize_name(name: str) -> str:
    """Normalize an ingredient name: lowercase, strip, and resolve aliases."""
    name = name.strip().lower()
    aliases = _load_aliases()
    return aliases.get(name, name)

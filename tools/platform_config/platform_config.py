"""platform_config — loader for per-platform configuration files.

Each platform is defined in a JSON file under config/platforms/:

    config/platforms/x.json
    config/platforms/linkedin.json
    config/platforms/instagram.json
    config/platforms/facebook.json
    config/platforms/mastodon.json

All files conform to config/platforms/platform.schema.json.

Public API
----------
    load_platform(name, config_dir=None) -> dict
        Return the config dict for a named platform.
        Raises ValueError for unrecognised names.
        Raises RuntimeError if the config file is missing or malformed.

    load_all_platforms(config_dir=None) -> dict[str, dict]
        Return a mapping of platform_id -> config dict for every platform file
        found in config_dir. Useful for tooling and tests.

    list_platforms(config_dir=None) -> list[str]
        Return a sorted list of all platform_id values available.

    resolve_alias(name, config_dir=None) -> str
        Resolve a platform alias (e.g. "x", "twitter/x") to a canonical
        platform_id (e.g. "twitter"). Raises ValueError if not found.

Name resolution
---------------
load_platform() accepts both canonical platform_id values and aliases defined
in the "aliases" array of each config file. Resolution is case-insensitive.
"""

import json
import os
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Default config directory — resolved relative to this file's location so the
# loader works regardless of the caller's working directory.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent          # tools/platform_config/
_REPO_ROOT = _HERE.parent.parent                  # repo root
_DEFAULT_CONFIG_DIR = _REPO_ROOT / "config" / "platforms"


def _config_dir(config_dir: Optional[str | Path]) -> Path:
    """Return a resolved Path to the config directory."""
    if config_dir is None:
        return _DEFAULT_CONFIG_DIR
    return Path(config_dir).resolve()


def _load_json_file(path: Path) -> dict:
    """Read and parse a JSON file; raise RuntimeError on any failure."""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise RuntimeError(f"Platform config file not found: {path}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Platform config file is not valid JSON ({path}): {exc}")


# ---------------------------------------------------------------------------
# Alias index — built lazily and cached per config_dir path
# ---------------------------------------------------------------------------

_alias_cache: dict[str, dict[str, str]] = {}   # config_dir_str -> {alias_lower: platform_id}


def _build_alias_index(config_dir: Path) -> dict[str, str]:
    """Return a mapping of alias_lower -> platform_id for all config files."""
    index: dict[str, str] = {}
    for json_path in sorted(config_dir.glob("*.json")):
        if json_path.name == "platform.schema.json":
            continue
        try:
            cfg = _load_json_file(json_path)
        except RuntimeError:
            continue  # skip malformed files when building the index
        pid = cfg.get("platform_id", "")
        if not pid:
            continue
        for alias in cfg.get("aliases", [pid]):
            index[str(alias).lower()] = pid
    return index


def _get_alias_index(config_dir: Path) -> dict[str, str]:
    key = str(config_dir)
    if key not in _alias_cache:
        _alias_cache[key] = _build_alias_index(config_dir)
    return _alias_cache[key]


def _clear_alias_cache() -> None:
    """Clear the alias cache. Used by tests that inject a custom config_dir."""
    _alias_cache.clear()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_alias(name: str, config_dir: Optional[str | Path] = None) -> str:
    """Resolve a platform name or alias to a canonical platform_id.

    Args:
        name:       Platform name or alias, case-insensitive.
        config_dir: Path to directory containing platform JSON files.
                    Defaults to config/platforms/ relative to the repo root.

    Returns:
        The canonical platform_id string (e.g. "twitter").

    Raises:
        ValueError: if name does not match any known platform or alias.
    """
    cdir = _config_dir(config_dir)
    index = _get_alias_index(cdir)
    canonical = index.get(name.strip().lower())
    if canonical is None:
        known = sorted(set(index.values()))
        raise ValueError(
            f"Unknown platform '{name}'. Known platforms: {', '.join(known)}."
        )
    return canonical


def load_platform(name: str, config_dir: Optional[str | Path] = None) -> dict:
    """Return the config dict for a named platform.

    Args:
        name:       Platform name or alias (case-insensitive).
                    Accepts canonical IDs ("twitter") and aliases ("x", "twitter/x").
        config_dir: Path to directory containing platform JSON files.
                    Defaults to config/platforms/ relative to the repo root.

    Returns:
        The parsed platform config dict, exactly as stored in the JSON file.

    Raises:
        ValueError:   if name is not a recognised platform or alias.
        RuntimeError: if the JSON file is missing or malformed.
    """
    cdir = _config_dir(config_dir)
    platform_id = resolve_alias(name, cdir)

    # Find the file whose platform_id matches. The filename convention is
    # <platform_id>.json, but we fall back to scanning if needed.
    candidate = cdir / f"{platform_id}.json"
    if not candidate.exists():
        # Fallback: scan all files for a matching platform_id field
        for json_path in sorted(cdir.glob("*.json")):
            if json_path.name == "platform.schema.json":
                continue
            cfg = _load_json_file(json_path)
            if cfg.get("platform_id") == platform_id:
                return cfg
        raise RuntimeError(
            f"Config file for platform '{platform_id}' not found in {cdir}."
        )

    return _load_json_file(candidate)


def load_all_platforms(config_dir: Optional[str | Path] = None) -> dict[str, dict]:
    """Return a mapping of platform_id -> config dict for all platform files.

    Skips platform.schema.json and any files that fail to parse.

    Args:
        config_dir: Path to directory containing platform JSON files.
                    Defaults to config/platforms/ relative to the repo root.

    Returns:
        dict mapping canonical platform_id strings to their config dicts.
    """
    cdir = _config_dir(config_dir)
    result: dict[str, dict] = {}
    for json_path in sorted(cdir.glob("*.json")):
        if json_path.name == "platform.schema.json":
            continue
        try:
            cfg = _load_json_file(json_path)
        except RuntimeError:
            continue
        pid = cfg.get("platform_id")
        if pid:
            result[pid] = cfg
    return result


def list_platforms(config_dir: Optional[str | Path] = None) -> list[str]:
    """Return a sorted list of all available platform_id values.

    Args:
        config_dir: Path to directory containing platform JSON files.
                    Defaults to config/platforms/ relative to the repo root.

    Returns:
        Sorted list of canonical platform_id strings.
    """
    return sorted(load_all_platforms(config_dir).keys())

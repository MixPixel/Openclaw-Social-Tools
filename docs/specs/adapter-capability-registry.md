# Spec: adapter-capability-registry

## Purpose

Provides a typed, validated contract for every platform adapter and a
registry that answers two questions at runtime:

1. **"What can this platform do?"** — structured capability declarations
   per adapter, queryable without importing or instantiating the adapter.
2. **"Does this platform support X?"** — a clean failure path
   (`CapabilityError`) for callers that must abort when a capability is
   absent, and a boolean query path (`supports_capability`) for callers
   that want to branch.

This layer sits between the raw adapter modules (which hold HTTP logic) and
the tools that call them (which should not need to know whether threads,
asset uploads, or preview generation are available on a given platform).

---

## Why It Exists

Before this layer, the registry knew only how to return an adapter callable.
It had no concept of what a given adapter could do. Problems that follow:

- Callers cannot ask "does twitter support threads?" without importing and
  reading the adapter source.
- There is no clean failure mode for "twitter does not support preview_post"
  — callers get a NotImplementedError or silent wrong behaviour.
- `_PLATFORM_TO_MODULE` in `registry.py` was a second list of platform IDs
  that could drift out of sync with the actual adapter modules.

The capability registry eliminates both problems.

---

## File Structure

```
tools/platform_adapters/
    contract.py            capability constants + AdapterDefinition dataclass
                           + validate_definition()
    capability_registry.py registry of definitions + query functions +
                           CapabilityError
    registry.py            (updated) now derives module_path from
                           capability_registry instead of a local dict
    __init__.py            (updated) exports all new public symbols
```

---

## Capability Constants

Defined in `contract.py`.  All values are lowercase strings.

| Constant | Value | Meaning |
|---|---|---|
| `PUBLISH_POST` | `"publish_post"` | Post a single status/post to the platform |
| `PUBLISH_THREAD` | `"publish_thread"` | Post a thread (sequence of linked posts) |
| `UPLOAD_ASSET` | `"upload_asset"` | Upload a media asset independently of posting |
| `VALIDATE_POST` | `"validate_post"` | Validate content against platform rules without publishing |
| `PREVIEW_POST` | `"preview_post"` | Generate a preview without publishing |

`ALL_CAPABILITIES` is a `frozenset` containing all five.

---

## AdapterDefinition

Defined as a `frozen=True` dataclass in `contract.py`.  All fields are
immutable after construction.

| Field | Type | Description |
|---|---|---|
| `platform_id` | str | Canonical platform ID — matches `config/platforms/<id>.json` |
| `display_name` | str | Human-readable name for error messages |
| `capabilities` | frozenset[str] | Capabilities this adapter declares (subset of `ALL_CAPABILITIES`) |
| `required_credential_keys` | tuple[str, ...] | Env var names required — matches `REQUIRED_CREDENTIALS` in the platform module |
| `module_path` | str | Fully qualified Python import path (e.g. `"tools.platform_adapters.twitter"`) |
| `media_formats` | frozenset[str] | Lowercase file extensions without dot (e.g. `"jpeg"`, `"mp4"`) |

`validate_definition(defn)` checks all fields and raises `ValueError` if any
are malformed.  It is called automatically during `_register()` at import time,
so a bad definition surfaces as an `ImportError` before any test or tool runs.

---

## Registry

`capability_registry.py` populates `_REGISTRY` at module load time by calling
`_register()` for each of the five platforms.

### Registered platforms and their declared capabilities

| Platform | `PUBLISH_POST` | `UPLOAD_ASSET` | `VALIDATE_POST` | `PUBLISH_THREAD` | `PREVIEW_POST` |
|---|:---:|:---:|:---:|:---:|:---:|
| `twitter` | ✓ | ✓ | ✓ | — | — |
| `linkedin` | ✓ | ✓ | ✓ | — | — |
| `instagram` | ✓ | ✓ | ✓ | — | — |
| `facebook` | ✓ | ✓ | ✓ | — | — |
| `mastodon` | ✓ | ✓ | ✓ | — | — |

`PUBLISH_THREAD` and `PREVIEW_POST` are defined in `ALL_CAPABILITIES` and will
be declared once the corresponding adapter logic is implemented.

---

## Public API

All symbols are re-exported via `tools.platform_adapters.__init__`.

### `get_definition(platform_id) -> AdapterDefinition`

Return the definition for a named platform.

```python
from tools.platform_adapters import get_definition
defn = get_definition("twitter")
print(defn.display_name)       # "Twitter / X"
print(defn.module_path)        # "tools.platform_adapters.twitter"
print(sorted(defn.capabilities))  # ['publish_post', 'upload_asset', 'validate_post']
```

Raises `ValueError` for unknown platform IDs.

### `list_platforms() -> list[str]`

Return a sorted list of all registered canonical platform IDs.

```python
from tools.platform_adapters import list_platforms
list_platforms()   # ['facebook', 'instagram', 'linkedin', 'mastodon', 'twitter']
```

### `list_capabilities(platform_id) -> list[str]`

Return a sorted list of capabilities declared for a platform.

```python
from tools.platform_adapters import list_capabilities
list_capabilities("twitter")   # ['publish_post', 'upload_asset', 'validate_post']
```

Raises `ValueError` for unknown platforms.

### `supports_capability(platform_id, capability) -> bool`

Return `True` if the platform declares the named capability.  Returns `False`
for any undeclared capability including unrecognised capability strings.

```python
from tools.platform_adapters import supports_capability, PUBLISH_THREAD
supports_capability("twitter", PUBLISH_THREAD)   # False
```

Raises `ValueError` for unknown platforms.

### `require_capability(platform_id, capability) -> None`

Assert that a platform supports a capability.  Use this as a guard at the top
of any function that must abort when the capability is absent.

```python
from tools.platform_adapters import require_capability, PREVIEW_POST, CapabilityError

try:
    require_capability("twitter", PREVIEW_POST)
except CapabilityError as exc:
    print(exc)   # Platform 'twitter' does not support capability 'preview_post'. ...
```

Raises `ValueError` for unknown platforms.  Raises `CapabilityError` for
known platforms that do not declare the capability.

---

## CapabilityError vs ValueError

| Exception | Cause | Appropriate response |
|---|---|---|
| `ValueError` | Unknown `platform_id` — developer/config error | Fix the platform ID in the calling code |
| `CapabilityError` | Known platform, capability not declared | Gracefully skip, fall back, or surface to user |

---

## Relationship to Existing registry.py

`registry.py` is the adapter callable factory used by `publish_post`.
Before Step 4 it maintained its own `_PLATFORM_TO_MODULE` dict, duplicating
the list of supported platforms.

After Step 4, `registry.py` calls `capability_registry.get_definition(platform_id)`
to obtain the `module_path` before importing.  The dict has been removed.
Both layers share a single source of truth.

The public API of `registry.py` (`get_adapter`, `get_dispatch_adapter`) is
unchanged.  All existing tests continue to pass.

---

## How to Add a New Platform

1. Create `config/platforms/<platform_id>.json` (platform config layer).
2. Create `tools/platform_adapters/<platform_id>.py` with the adapter skeleton.
3. Add an `_register(AdapterDefinition(...))` call in `capability_registry.py`
   with the correct `capabilities`, `required_credential_keys`, and `module_path`.
4. No changes to `registry.py` are required — it derives `module_path` from
   the definition automatically.
5. Add tests to `tests/test_adapter_capability_registry.py`.

---

## Placeholders / Future Work

- `PUBLISH_THREAD`: Twitter/X supports threads natively. Declare this
  capability once `TwitterAdapter.__call__` implements the chained-post logic.
- `PREVIEW_POST`: No current adapter implements preview. Declare once
  implemented. The capability is already in `ALL_CAPABILITIES`.
- `media_formats` per platform: values are derived from `config/platforms/*.json`
  media rules. A future migration could load them from the platform config
  file dynamically instead of repeating them in `capability_registry.py`.

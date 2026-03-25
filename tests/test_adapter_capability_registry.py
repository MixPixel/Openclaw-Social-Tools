"""Tests for the adapter capability contract and registry layer.

Coverage:
  TestCapabilityConstants      — constants are non-empty strings, unique,
                                 all present in ALL_CAPABILITIES
  TestAdapterDefinition        — dataclass is frozen, fields have correct types,
                                 default media_formats is empty frozenset
  TestValidateDefinition       — valid definition passes; empty platform_id,
                                 empty display_name, wrong capabilities type,
                                 unknown capability, wrong credential_keys type,
                                 empty module_path, wrong media_formats type
                                 all raise ValueError; non-AdapterDefinition raises
  TestRegistryListPlatforms    — 5 platforms, sorted, matches expected canonical IDs
  TestGetDefinition            — happy path for each platform; unknown raises
                                 ValueError containing the platform name; error
                                 message lists registered platforms
  TestListCapabilities         — sorted, all entries are in ALL_CAPABILITIES,
                                 unknown platform raises ValueError
  TestSupportsCapability       — True for declared capability, False for absent,
                                 False for unknown capability string,
                                 ValueError for unknown platform
  TestRequireCapability        — succeeds silently for declared capability,
                                 raises CapabilityError for absent capability,
                                 raises ValueError for unknown platform,
                                 CapabilityError message names capability and platform
  TestDefinitionIntegrity      — every registered definition passes
                                 validate_definition; platform_id matches registry
                                 key; capabilities ⊆ ALL_CAPABILITIES;
                                 required_credential_keys is non-empty tuple;
                                 module_path is importable; media_formats is frozenset
  TestPublishPostCoverage      — every registered platform declares PUBLISH_POST
  TestUndeclaredCapabilities   — PUBLISH_THREAD and PREVIEW_POST are not declared
                                 by any current platform adapter
  TestCredentialKeyConsistency — required_credential_keys in each definition
                                 matches REQUIRED_CREDENTIALS in the platform module
  TestRegistryPlatformCoverage — capability_registry and get_adapter() agree on
                                 which platform IDs are valid (no orphaned modules)
  TestPublicApiExports         — all expected symbols importable directly from
                                 tools.platform_adapters
"""

import importlib
import unittest

from tools.platform_adapters import (
    # Capability constants
    ALL_CAPABILITIES,
    PREVIEW_POST,
    PUBLISH_POST,
    PUBLISH_THREAD,
    UPLOAD_ASSET,
    VALIDATE_POST,
    # Contract
    AdapterDefinition,
    validate_definition,
    # Registry
    CapabilityError,
    get_definition,
    list_capabilities,
    list_platforms,
    require_capability,
    supports_capability,
    # Existing adapter API (must not be broken)
    get_adapter,
    get_dispatch_adapter,
)

_ALL_PLATFORMS = ["facebook", "instagram", "linkedin", "mastodon", "twitter"]

_CAPABILITY_CONSTANTS = [
    PUBLISH_POST,
    PUBLISH_THREAD,
    UPLOAD_ASSET,
    VALIDATE_POST,
    PREVIEW_POST,
]


# ---------------------------------------------------------------------------
# TestCapabilityConstants
# ---------------------------------------------------------------------------

class TestCapabilityConstants(unittest.TestCase):

    def test_constants_are_strings(self):
        for cap in _CAPABILITY_CONSTANTS:
            with self.subTest(cap=cap):
                self.assertIsInstance(cap, str)

    def test_constants_are_nonempty(self):
        for cap in _CAPABILITY_CONSTANTS:
            with self.subTest(cap=cap):
                self.assertTrue(cap.strip())

    def test_constants_are_unique(self):
        self.assertEqual(len(_CAPABILITY_CONSTANTS), len(set(_CAPABILITY_CONSTANTS)))

    def test_all_capabilities_is_frozenset(self):
        self.assertIsInstance(ALL_CAPABILITIES, frozenset)

    def test_all_capabilities_contains_every_constant(self):
        for cap in _CAPABILITY_CONSTANTS:
            with self.subTest(cap=cap):
                self.assertIn(cap, ALL_CAPABILITIES)

    def test_all_capabilities_has_correct_size(self):
        self.assertEqual(len(ALL_CAPABILITIES), len(_CAPABILITY_CONSTANTS))


# ---------------------------------------------------------------------------
# TestAdapterDefinition
# ---------------------------------------------------------------------------

class TestAdapterDefinition(unittest.TestCase):

    def _make_valid(self, **overrides) -> AdapterDefinition:
        defaults = dict(
            platform_id="testplatform",
            display_name="Test Platform",
            capabilities=frozenset({PUBLISH_POST}),
            required_credential_keys=("TEST_KEY",),
            module_path="tools.platform_adapters.stub",
        )
        defaults.update(overrides)
        return AdapterDefinition(**defaults)

    def test_creates_valid_definition(self):
        defn = self._make_valid()
        self.assertEqual(defn.platform_id, "testplatform")
        self.assertEqual(defn.display_name, "Test Platform")
        self.assertIn(PUBLISH_POST, defn.capabilities)

    def test_is_frozen(self):
        defn = self._make_valid()
        with self.assertRaises((AttributeError, TypeError)):
            defn.platform_id = "changed"  # type: ignore[misc]

    def test_default_media_formats_is_empty_frozenset(self):
        defn = self._make_valid()
        self.assertIsInstance(defn.media_formats, frozenset)
        self.assertEqual(len(defn.media_formats), 0)

    def test_media_formats_accepted(self):
        defn = self._make_valid(media_formats=frozenset({"jpeg", "png"}))
        self.assertEqual(defn.media_formats, frozenset({"jpeg", "png"}))


# ---------------------------------------------------------------------------
# TestValidateDefinition
# ---------------------------------------------------------------------------

class TestValidateDefinition(unittest.TestCase):

    def _make_valid(self, **overrides) -> AdapterDefinition:
        defaults = dict(
            platform_id="testplatform",
            display_name="Test Platform",
            capabilities=frozenset({PUBLISH_POST}),
            required_credential_keys=("TEST_KEY",),
            module_path="tools.platform_adapters.stub",
        )
        defaults.update(overrides)
        return AdapterDefinition(**defaults)

    def test_valid_definition_does_not_raise(self):
        validate_definition(self._make_valid())  # must not raise

    def test_all_capabilities_valid(self):
        defn = self._make_valid(capabilities=ALL_CAPABILITIES)
        validate_definition(defn)  # must not raise

    def test_non_adapter_definition_raises(self):
        with self.assertRaises(ValueError):
            validate_definition({"platform_id": "x"})  # type: ignore[arg-type]

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            validate_definition(None)  # type: ignore[arg-type]

    def test_empty_platform_id_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_definition(self._make_valid(platform_id=""))
        self.assertIn("platform_id", str(ctx.exception))

    def test_whitespace_platform_id_raises(self):
        with self.assertRaises(ValueError):
            validate_definition(self._make_valid(platform_id="   "))

    def test_empty_display_name_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_definition(self._make_valid(display_name=""))
        self.assertIn("display_name", str(ctx.exception))

    def test_capabilities_not_frozenset_raises(self):
        defn = AdapterDefinition(
            platform_id="p",
            display_name="P",
            capabilities=set({PUBLISH_POST}),  # type: ignore[arg-type]  — wrong type
            required_credential_keys=("K",),
            module_path="tools.platform_adapters.stub",
        )
        with self.assertRaises(ValueError) as ctx:
            validate_definition(defn)
        self.assertIn("capabilities", str(ctx.exception))

    def test_unknown_capability_raises(self):
        defn = self._make_valid(capabilities=frozenset({"NOT_A_REAL_CAPABILITY"}))
        with self.assertRaises(ValueError) as ctx:
            validate_definition(defn)
        self.assertIn("NOT_A_REAL_CAPABILITY", str(ctx.exception))

    def test_required_credential_keys_not_tuple_raises(self):
        defn = AdapterDefinition(
            platform_id="p",
            display_name="P",
            capabilities=frozenset({PUBLISH_POST}),
            required_credential_keys=["K"],  # type: ignore[arg-type]  — list, not tuple
            module_path="tools.platform_adapters.stub",
        )
        with self.assertRaises(ValueError) as ctx:
            validate_definition(defn)
        self.assertIn("required_credential_keys", str(ctx.exception))

    def test_empty_module_path_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_definition(self._make_valid(module_path=""))
        self.assertIn("module_path", str(ctx.exception))

    def test_media_formats_not_frozenset_raises(self):
        defn = AdapterDefinition(
            platform_id="p",
            display_name="P",
            capabilities=frozenset({PUBLISH_POST}),
            required_credential_keys=("K",),
            module_path="tools.platform_adapters.stub",
            media_formats={"jpeg", "png"},  # type: ignore[arg-type]  — set, not frozenset
        )
        with self.assertRaises(ValueError) as ctx:
            validate_definition(defn)
        self.assertIn("media_formats", str(ctx.exception))


# ---------------------------------------------------------------------------
# TestRegistryListPlatforms
# ---------------------------------------------------------------------------

class TestRegistryListPlatforms(unittest.TestCase):

    def test_returns_list(self):
        self.assertIsInstance(list_platforms(), list)

    def test_contains_five_platforms(self):
        self.assertEqual(len(list_platforms()), 5)

    def test_is_sorted(self):
        platforms = list_platforms()
        self.assertEqual(platforms, sorted(platforms))

    def test_contains_all_canonical_ids(self):
        platforms = set(list_platforms())
        for p in _ALL_PLATFORMS:
            with self.subTest(platform=p):
                self.assertIn(p, platforms)

    def test_does_not_contain_stub(self):
        self.assertNotIn("stub", list_platforms())

    def test_does_not_contain_x_alias(self):
        self.assertNotIn("x", list_platforms())


# ---------------------------------------------------------------------------
# TestGetDefinition
# ---------------------------------------------------------------------------

class TestGetDefinition(unittest.TestCase):

    def test_returns_adapter_definition_for_each_platform(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                self.assertIsInstance(defn, AdapterDefinition)

    def test_platform_id_matches_key(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                self.assertEqual(defn.platform_id, platform)

    def test_display_name_nonempty(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                self.assertTrue(defn.display_name.strip())

    def test_unknown_platform_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            get_definition("tiktok")
        self.assertIn("tiktok", str(ctx.exception))

    def test_unknown_platform_error_lists_registered(self):
        with self.assertRaises(ValueError) as ctx:
            get_definition("nonexistent")
        msg = str(ctx.exception)
        for p in _ALL_PLATFORMS:
            self.assertIn(p, msg)

    def test_empty_string_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_definition("")


# ---------------------------------------------------------------------------
# TestListCapabilities
# ---------------------------------------------------------------------------

class TestListCapabilities(unittest.TestCase):

    def test_returns_list_for_each_platform(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                caps = list_capabilities(platform)
                self.assertIsInstance(caps, list)

    def test_is_sorted(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                caps = list_capabilities(platform)
                self.assertEqual(caps, sorted(caps))

    def test_all_entries_are_known_capabilities(self):
        for platform in _ALL_PLATFORMS:
            for cap in list_capabilities(platform):
                with self.subTest(platform=platform, cap=cap):
                    self.assertIn(cap, ALL_CAPABILITIES)

    def test_unknown_platform_raises_value_error(self):
        with self.assertRaises(ValueError):
            list_capabilities("unknown_xyz")


# ---------------------------------------------------------------------------
# TestSupportsCapability
# ---------------------------------------------------------------------------

class TestSupportsCapability(unittest.TestCase):

    def test_publish_post_supported_on_all_platforms(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                self.assertTrue(supports_capability(platform, PUBLISH_POST))

    def test_upload_asset_supported_on_all_platforms(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                self.assertTrue(supports_capability(platform, UPLOAD_ASSET))

    def test_validate_post_supported_on_all_platforms(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                self.assertTrue(supports_capability(platform, VALIDATE_POST))

    def test_publish_thread_not_supported(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                self.assertFalse(supports_capability(platform, PUBLISH_THREAD))

    def test_preview_post_not_supported(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                self.assertFalse(supports_capability(platform, PREVIEW_POST))

    def test_unknown_capability_string_returns_false(self):
        self.assertFalse(supports_capability("twitter", "NOT_A_REAL_CAPABILITY"))

    def test_unknown_platform_raises_value_error(self):
        with self.assertRaises(ValueError):
            supports_capability("unknown_platform", PUBLISH_POST)


# ---------------------------------------------------------------------------
# TestRequireCapability
# ---------------------------------------------------------------------------

class TestRequireCapability(unittest.TestCase):

    def test_succeeds_silently_for_declared_capability(self):
        try:
            require_capability("twitter", PUBLISH_POST)
        except (CapabilityError, ValueError) as exc:
            self.fail(f"require_capability raised unexpectedly: {exc}")

    def test_returns_none_on_success(self):
        result = require_capability("twitter", PUBLISH_POST)
        self.assertIsNone(result)

    def test_raises_capability_error_for_absent_capability(self):
        with self.assertRaises(CapabilityError):
            require_capability("twitter", PUBLISH_THREAD)

    def test_capability_error_names_capability(self):
        with self.assertRaises(CapabilityError) as ctx:
            require_capability("twitter", PUBLISH_THREAD)
        self.assertIn(PUBLISH_THREAD, str(ctx.exception))

    def test_capability_error_names_platform(self):
        with self.assertRaises(CapabilityError) as ctx:
            require_capability("twitter", PUBLISH_THREAD)
        self.assertIn("twitter", str(ctx.exception))

    def test_capability_error_is_not_value_error(self):
        # CapabilityError must not be a subclass of ValueError — callers can
        # catch them independently.
        self.assertFalse(issubclass(CapabilityError, ValueError))

    def test_unknown_platform_raises_value_error_not_capability_error(self):
        with self.assertRaises(ValueError):
            require_capability("tiktok", PUBLISH_POST)
        # Must NOT be CapabilityError
        try:
            require_capability("tiktok", PUBLISH_POST)
        except CapabilityError:
            self.fail("Unknown platform should raise ValueError, not CapabilityError")
        except ValueError:
            pass  # expected

    def test_require_all_current_capabilities_all_platforms(self):
        for platform in _ALL_PLATFORMS:
            for cap in (PUBLISH_POST, UPLOAD_ASSET, VALIDATE_POST):
                with self.subTest(platform=platform, cap=cap):
                    require_capability(platform, cap)  # must not raise


# ---------------------------------------------------------------------------
# TestDefinitionIntegrity
# ---------------------------------------------------------------------------

class TestDefinitionIntegrity(unittest.TestCase):
    """Every registered definition is internally consistent."""

    def test_validate_definition_passes_for_all(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                validate_definition(defn)  # must not raise

    def test_capabilities_subset_of_all_capabilities(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                self.assertTrue(
                    defn.capabilities.issubset(ALL_CAPABILITIES),
                    f"{platform} capabilities {defn.capabilities} "
                    f"not all in ALL_CAPABILITIES",
                )

    def test_required_credential_keys_nonempty_tuple(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                self.assertIsInstance(defn.required_credential_keys, tuple)
                self.assertGreater(
                    len(defn.required_credential_keys), 0,
                    f"{platform}.required_credential_keys must not be empty",
                )

    def test_module_path_is_importable(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                try:
                    importlib.import_module(defn.module_path)
                except ImportError as exc:
                    self.fail(
                        f"module_path '{defn.module_path}' for '{platform}' "
                        f"is not importable: {exc}"
                    )

    def test_media_formats_is_frozenset(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                self.assertIsInstance(defn.media_formats, frozenset)

    def test_media_formats_nonempty(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                self.assertGreater(
                    len(defn.media_formats), 0,
                    f"{platform}.media_formats should not be empty",
                )


# ---------------------------------------------------------------------------
# TestPublishPostCoverage
# ---------------------------------------------------------------------------

class TestPublishPostCoverage(unittest.TestCase):
    """PUBLISH_POST must be declared by every registered adapter."""

    def test_all_platforms_declare_publish_post(self):
        for platform in list_platforms():
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                self.assertIn(
                    PUBLISH_POST,
                    defn.capabilities,
                    f"Platform '{platform}' is registered but does not declare "
                    f"PUBLISH_POST — every adapter must at minimum support posting.",
                )


# ---------------------------------------------------------------------------
# TestUndeclaredCapabilities
# ---------------------------------------------------------------------------

class TestUndeclaredCapabilities(unittest.TestCase):
    """PUBLISH_THREAD and PREVIEW_POST are not yet implemented."""

    def test_no_platform_declares_publish_thread(self):
        for platform in list_platforms():
            with self.subTest(platform=platform):
                self.assertFalse(
                    supports_capability(platform, PUBLISH_THREAD),
                    f"Platform '{platform}' unexpectedly declares PUBLISH_THREAD. "
                    "Update this test when thread support is implemented.",
                )

    def test_no_platform_declares_preview_post(self):
        for platform in list_platforms():
            with self.subTest(platform=platform):
                self.assertFalse(
                    supports_capability(platform, PREVIEW_POST),
                    f"Platform '{platform}' unexpectedly declares PREVIEW_POST. "
                    "Update this test when preview support is implemented.",
                )


# ---------------------------------------------------------------------------
# TestCredentialKeyConsistency
# ---------------------------------------------------------------------------

class TestCredentialKeyConsistency(unittest.TestCase):
    """required_credential_keys in each definition matches the platform module."""

    def test_credential_keys_match_platform_module(self):
        for platform in _ALL_PLATFORMS:
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                mod = importlib.import_module(defn.module_path)
                self.assertEqual(
                    defn.required_credential_keys,
                    mod.REQUIRED_CREDENTIALS,
                    f"capability_registry definition for '{platform}' has "
                    f"required_credential_keys {defn.required_credential_keys} "
                    f"but {defn.module_path}.REQUIRED_CREDENTIALS is "
                    f"{mod.REQUIRED_CREDENTIALS}",
                )


# ---------------------------------------------------------------------------
# TestRegistryPlatformCoverage
# ---------------------------------------------------------------------------

class TestRegistryPlatformCoverage(unittest.TestCase):
    """capability_registry and get_adapter() agree on supported platform IDs."""

    def test_all_registered_platforms_resolvable_by_get_adapter(self):
        """get_adapter raises ValueError for unknown platforms but not for
        registered ones (using empty credentials so AUTH_ERROR is returned,
        not NotImplementedError being raised prematurely)."""
        for platform in list_platforms():
            with self.subTest(platform=platform):
                defn = get_definition(platform)
                creds = {k: "" for k in defn.required_credential_keys}
                try:
                    adapter = get_adapter(platform, credentials=creds)
                    self.assertTrue(callable(adapter))
                except ValueError:
                    self.fail(
                        f"get_adapter('{platform}') raised ValueError but "
                        f"'{platform}' is registered in capability_registry."
                    )

    def test_get_adapter_unknown_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_adapter("not_a_real_platform")


# ---------------------------------------------------------------------------
# TestPublicApiExports
# ---------------------------------------------------------------------------

class TestPublicApiExports(unittest.TestCase):
    """All Step-4 symbols are importable directly from tools.platform_adapters."""

    def _import(self, name: str):
        import tools.platform_adapters as pa
        self.assertTrue(
            hasattr(pa, name),
            f"tools.platform_adapters does not export '{name}'",
        )

    def test_exports_capability_constants(self):
        for name in (
            "PUBLISH_POST", "PUBLISH_THREAD", "UPLOAD_ASSET",
            "VALIDATE_POST", "PREVIEW_POST", "ALL_CAPABILITIES",
        ):
            with self.subTest(symbol=name):
                self._import(name)

    def test_exports_adapter_definition(self):
        self._import("AdapterDefinition")

    def test_exports_validate_definition(self):
        self._import("validate_definition")

    def test_exports_capability_error(self):
        self._import("CapabilityError")

    def test_exports_registry_functions(self):
        for name in (
            "get_definition", "list_platforms", "list_capabilities",
            "supports_capability", "require_capability",
        ):
            with self.subTest(symbol=name):
                self._import(name)

    def test_existing_exports_still_present(self):
        """Step 4 must not remove any previously exported symbol."""
        for name in (
            "AUTH_ERROR", "UNKNOWN_ERROR", "ALL_ERROR_CODES",
            "StubAdapter", "get_adapter", "get_dispatch_adapter",
            "is_retryable", "classify_http_error", "validate_adapter_result",
        ):
            with self.subTest(symbol=name):
                self._import(name)


if __name__ == "__main__":
    unittest.main()

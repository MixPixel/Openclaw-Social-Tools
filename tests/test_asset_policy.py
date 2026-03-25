"""Tests for config/asset_policy.json and config/asset_policy.schema.json.

Coverage:
  TestAssetPolicyShape        — asset_policy.json loads, all required fields
                                present, correct types
  TestUsagePolicies           — usage_policies dict non-empty; each entry has
                                required keys and a valid edit_rule enum value
  TestKnownAssetTypes         — the seven conventional asset types are present
  TestProvenanceFields        — approved_source_domains, forbidden_url_patterns,
                                required_license_fields are lists of strings
  TestSchemaShape             — asset_policy.schema.json has expected structure
                                and defines the UsagePolicy in definitions
"""

import json
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_POLICY_JSON = _REPO_ROOT / "config" / "asset_policy.json"
_SCHEMA_JSON = _REPO_ROOT / "config" / "asset_policy.schema.json"

_REQUIRED_TOP_LEVEL = {
    "version",
    "approved_source_domains",
    "forbidden_url_patterns",
    "required_license_fields",
    "require_alt_text",
    "usage_policies",
}

_REQUIRED_POLICY_KEYS = {
    "edit_rule",
    "require_license",
    "require_attribution",
    "allowed_contexts",
}

_VALID_EDIT_RULES = {
    "locked",
    "resizable_only",
    "croppable_only",
    "editable",
    "reference_only",
}

_CONVENTIONAL_ASSET_TYPES = {
    "logo",
    "product_photo",
    "website_screenshot",
    "generated_graphic",
    "customer_photo",
    "stock_photo",
    "icon",
}


def _load_policy() -> dict:
    with open(_POLICY_JSON, encoding="utf-8") as f:
        return json.load(f)


def _load_schema() -> dict:
    with open(_SCHEMA_JSON, encoding="utf-8") as f:
        return json.load(f)


class TestAssetPolicyShape(unittest.TestCase):
    """asset_policy.json loads cleanly and has the required top-level shape."""

    def setUp(self):
        self.policy = _load_policy()

    def test_is_dict(self):
        self.assertIsInstance(self.policy, dict)

    def test_required_fields_present(self):
        missing = _REQUIRED_TOP_LEVEL - self.policy.keys()
        self.assertFalse(missing, f"Missing required fields: {missing}")

    def test_version_nonempty_string(self):
        self.assertIsInstance(self.policy["version"], str)
        self.assertTrue(self.policy["version"].strip())

    def test_require_alt_text_is_bool(self):
        self.assertIsInstance(self.policy["require_alt_text"], bool)

    def test_usage_policies_is_dict(self):
        self.assertIsInstance(self.policy["usage_policies"], dict)

    def test_usage_policies_nonempty(self):
        self.assertTrue(len(self.policy["usage_policies"]) >= 1)

    def test_no_unexpected_top_level_keys(self):
        allowed = _REQUIRED_TOP_LEVEL | {"_notes"}
        unexpected = self.policy.keys() - allowed
        self.assertFalse(unexpected, f"Unexpected top-level keys: {unexpected}")


class TestUsagePolicies(unittest.TestCase):
    """Each entry in usage_policies has the required shape and a valid edit_rule."""

    def setUp(self):
        self.policies = _load_policy()["usage_policies"]

    def test_each_policy_has_required_keys(self):
        for asset_type, policy in self.policies.items():
            with self.subTest(asset_type=asset_type):
                missing = _REQUIRED_POLICY_KEYS - policy.keys()
                self.assertFalse(
                    missing,
                    f"usage_policies['{asset_type}'] missing keys: {missing}",
                )

    def test_edit_rule_is_valid_enum(self):
        for asset_type, policy in self.policies.items():
            with self.subTest(asset_type=asset_type):
                self.assertIn(
                    policy["edit_rule"],
                    _VALID_EDIT_RULES,
                    f"usage_policies['{asset_type}'].edit_rule = {policy['edit_rule']!r} "
                    f"is not a valid edit_rule",
                )

    def test_require_license_is_bool(self):
        for asset_type, policy in self.policies.items():
            with self.subTest(asset_type=asset_type):
                self.assertIsInstance(policy["require_license"], bool)

    def test_require_attribution_is_bool(self):
        for asset_type, policy in self.policies.items():
            with self.subTest(asset_type=asset_type):
                self.assertIsInstance(policy["require_attribution"], bool)

    def test_allowed_contexts_is_list(self):
        for asset_type, policy in self.policies.items():
            with self.subTest(asset_type=asset_type):
                self.assertIsInstance(policy["allowed_contexts"], list)

    def test_allowed_contexts_items_are_strings(self):
        for asset_type, policy in self.policies.items():
            for ctx in policy["allowed_contexts"]:
                with self.subTest(asset_type=asset_type, context=ctx):
                    self.assertIsInstance(ctx, str)

    def test_no_unexpected_policy_keys(self):
        allowed = _REQUIRED_POLICY_KEYS | {"_notes"}
        for asset_type, policy in self.policies.items():
            with self.subTest(asset_type=asset_type):
                unexpected = policy.keys() - allowed
                self.assertFalse(
                    unexpected,
                    f"usage_policies['{asset_type}'] has unexpected keys: {unexpected}",
                )


class TestKnownAssetTypes(unittest.TestCase):
    """The seven conventional asset types are all present."""

    def setUp(self):
        self.policies = _load_policy()["usage_policies"]

    def test_conventional_types_present(self):
        missing = _CONVENTIONAL_ASSET_TYPES - self.policies.keys()
        self.assertFalse(
            missing,
            f"Conventional asset types missing from usage_policies: {missing}",
        )

    def test_logo_is_locked(self):
        self.assertEqual(self.policies["logo"]["edit_rule"], "locked")

    def test_website_screenshot_is_reference_only(self):
        self.assertEqual(self.policies["website_screenshot"]["edit_rule"], "reference_only")

    def test_generated_graphic_is_editable(self):
        self.assertEqual(self.policies["generated_graphic"]["edit_rule"], "editable")

    def test_customer_photo_requires_license(self):
        self.assertTrue(self.policies["customer_photo"]["require_license"])

    def test_customer_photo_requires_attribution(self):
        self.assertTrue(self.policies["customer_photo"]["require_attribution"])


class TestProvenanceFields(unittest.TestCase):
    """Provenance/licensing fields are lists of strings."""

    def setUp(self):
        self.policy = _load_policy()

    def test_approved_source_domains_is_list(self):
        self.assertIsInstance(self.policy["approved_source_domains"], list)

    def test_approved_source_domains_items_are_strings(self):
        for item in self.policy["approved_source_domains"]:
            self.assertIsInstance(item, str)

    def test_forbidden_url_patterns_is_list(self):
        self.assertIsInstance(self.policy["forbidden_url_patterns"], list)

    def test_forbidden_url_patterns_items_are_strings(self):
        for item in self.policy["forbidden_url_patterns"]:
            self.assertIsInstance(item, str)

    def test_required_license_fields_is_list(self):
        self.assertIsInstance(self.policy["required_license_fields"], list)

    def test_required_license_fields_items_are_strings(self):
        for item in self.policy["required_license_fields"]:
            self.assertIsInstance(item, str)

    def test_required_license_fields_nonempty(self):
        self.assertTrue(
            len(self.policy["required_license_fields"]) >= 1,
            "required_license_fields must have at least one field",
        )


class TestSchemaShape(unittest.TestCase):
    """asset_policy.schema.json has expected structure."""

    def setUp(self):
        self.schema = _load_schema()

    def test_is_dict(self):
        self.assertIsInstance(self.schema, dict)

    def test_title_is_asset_policy(self):
        self.assertEqual(self.schema.get("title"), "AssetPolicy")

    def test_type_is_object(self):
        self.assertEqual(self.schema.get("type"), "object")

    def test_has_required_array(self):
        self.assertIsInstance(self.schema.get("required"), list)

    def test_schema_required_covers_policy_fields(self):
        schema_required = set(self.schema.get("required", []))
        missing = _REQUIRED_TOP_LEVEL - schema_required
        self.assertFalse(
            missing,
            f"Schema required[] missing: {missing}",
        )

    def test_additional_properties_false(self):
        self.assertFalse(self.schema.get("additionalProperties"))

    def test_defines_usage_policy(self):
        defs = self.schema.get("definitions", {})
        self.assertIn("UsagePolicy", defs)

    def test_usage_policy_defines_edit_rule_enum(self):
        usage_policy = self.schema["definitions"]["UsagePolicy"]
        props = usage_policy.get("properties", {})
        self.assertIn("edit_rule", props)
        self.assertIn("enum", props["edit_rule"])

    def test_edit_rule_enum_matches_valid_set(self):
        edit_rule_enum = set(
            self.schema["definitions"]["UsagePolicy"]["properties"]["edit_rule"]["enum"]
        )
        self.assertEqual(edit_rule_enum, _VALID_EDIT_RULES)

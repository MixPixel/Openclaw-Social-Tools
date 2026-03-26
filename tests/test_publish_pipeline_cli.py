"""Tests for the publish_pipeline CLI (python -m tools.publish_pipeline).

Coverage:
  TestValidInput        — valid post JSON → publish_to_platform called,
                          result JSON on stdout, exit 0 on success / 1 on failure
  TestInvalidJson       — non-JSON stdin → structured error result, exit 1
  TestCredentials       — CLI always passes credentials=None so adapters read env
  TestOutputFormat      — stdout is valid JSON, contains all required fields
  TestExitCodes         — exit 0 on success, exit 1 on any failure path
  TestSubprocess        — end-to-end via subprocess for real stdin/stdout/exit
"""

import io
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from tools.publish_pipeline.__main__ import _main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUCCESS_RESULT = {
    "success":           True,
    "platform":          "twitter",
    "post_id":           "tweet-1",
    "character_count":   16,
    "validation_errors": [],
    "media_results":     [],
    "errors":            [],
    "warnings":          [],
}

_FAILURE_RESULT = {
    "success":           False,
    "platform":          "twitter",
    "post_id":           None,
    "character_count":   None,
    "validation_errors": [{"code": "CHARACTER_LIMIT_EXCEEDED", "message": "too long"}],
    "media_results":     [],
    "errors":            [],
    "warnings":          [],
}


def _run_main(stdin_text: str, mock_result=None):
    """Run _main() with patched stdin/stdout; return (exit_code, parsed_output)."""
    target = "tools.publish_pipeline.__main__.publish_to_platform"
    captured = io.StringIO()

    ctx = patch(target, return_value=mock_result) if mock_result is not None else patch(target)

    with ctx as mock_fn, \
         patch("sys.stdin", io.StringIO(stdin_text)), \
         patch("sys.stdout", captured):
        try:
            _main()
            exit_code = 0
        except SystemExit as exc:
            exit_code = exc.code

    captured.seek(0)
    raw = captured.read()
    try:
        output = json.loads(raw)
    except json.JSONDecodeError:
        output = raw

    return exit_code, output, mock_fn


# ---------------------------------------------------------------------------
# TestValidInput
# ---------------------------------------------------------------------------

class TestValidInput(unittest.TestCase):

    def test_publish_to_platform_called_once(self):
        post = {"platform": "twitter", "content": "Hello!"}
        _, _, mock_fn = _run_main(json.dumps(post), mock_result=_SUCCESS_RESULT)
        mock_fn.assert_called_once()

    def test_post_dict_passed_to_pipeline(self):
        post = {"platform": "twitter", "content": "Hello!"}
        _, _, mock_fn = _run_main(json.dumps(post), mock_result=_SUCCESS_RESULT)
        called_post = mock_fn.call_args[0][0]
        self.assertEqual(called_post, post)

    def test_credentials_none_passed_to_pipeline(self):
        """CLI always passes credentials=None so adapters read from os.environ."""
        post = {"platform": "twitter", "content": "Hello!"}
        _, _, mock_fn = _run_main(json.dumps(post), mock_result=_SUCCESS_RESULT)
        kwargs = mock_fn.call_args[1]
        self.assertIsNone(kwargs.get("credentials"))

    def test_result_written_to_stdout(self):
        post = {"platform": "twitter", "content": "Hello!"}
        _, output, _ = _run_main(json.dumps(post), mock_result=_SUCCESS_RESULT)
        self.assertEqual(output["post_id"], "tweet-1")

    def test_extra_fields_forwarded(self):
        """Hashtags, mentions, links in the post dict are passed through."""
        post = {
            "platform":  "twitter",
            "content":   "Hello!",
            "hashtags":  ["openclaw"],
            "mentions":  ["user"],
        }
        _, _, mock_fn = _run_main(json.dumps(post), mock_result=_SUCCESS_RESULT)
        called_post = mock_fn.call_args[0][0]
        self.assertEqual(called_post["hashtags"], ["openclaw"])


# ---------------------------------------------------------------------------
# TestInvalidJson
# ---------------------------------------------------------------------------

class TestInvalidJson(unittest.TestCase):

    def _run_bad(self, text):
        exit_code, output, _ = _run_main(text)
        return exit_code, output

    def test_non_json_exits_1(self):
        exit_code, _ = self._run_bad("not json at all")
        self.assertEqual(exit_code, 1)

    def test_non_json_result_has_success_false(self):
        _, output = self._run_bad("not json at all")
        self.assertFalse(output["success"])

    def test_non_json_error_code_is_invalid_input(self):
        _, output = self._run_bad("not json at all")
        codes = [e["code"] for e in output["errors"]]
        self.assertIn("INVALID_INPUT", codes)

    def test_empty_stdin_exits_1(self):
        exit_code, _ = self._run_bad("")
        self.assertEqual(exit_code, 1)

    def test_partial_json_exits_1(self):
        exit_code, _ = self._run_bad('{"platform": "twitter"')
        self.assertEqual(exit_code, 1)

    def test_invalid_json_result_has_all_required_fields(self):
        _, output = self._run_bad("bad")
        for field in ("success", "platform", "post_id", "character_count",
                      "validation_errors", "media_results", "errors", "warnings"):
            self.assertIn(field, output)

    def test_invalid_json_publish_not_called(self):
        _, _, mock_fn = _run_main("bad json", mock_result=_SUCCESS_RESULT)
        mock_fn.assert_not_called()


# ---------------------------------------------------------------------------
# TestOutputFormat
# ---------------------------------------------------------------------------

class TestOutputFormat(unittest.TestCase):

    def _output(self, result=None):
        post = {"platform": "twitter", "content": "Hi"}
        _, output, _ = _run_main(json.dumps(post), mock_result=result or _SUCCESS_RESULT)
        return output

    def test_output_is_dict(self):
        self.assertIsInstance(self._output(), dict)

    def test_output_has_success_field(self):
        self.assertIn("success", self._output())

    def test_output_has_platform_field(self):
        self.assertIn("platform", self._output())

    def test_output_has_errors_field(self):
        self.assertIn("errors", self._output())

    def test_output_has_validation_errors_field(self):
        self.assertIn("validation_errors", self._output())

    def test_output_has_media_results_field(self):
        self.assertIn("media_results", self._output())

    def test_failure_result_output_is_also_valid_json(self):
        output = self._output(_FAILURE_RESULT)
        self.assertIsInstance(output, dict)
        self.assertFalse(output["success"])


# ---------------------------------------------------------------------------
# TestExitCodes
# ---------------------------------------------------------------------------

class TestExitCodes(unittest.TestCase):

    def _exit(self, result):
        post = {"platform": "twitter", "content": "Hi"}
        exit_code, _, _ = _run_main(json.dumps(post), mock_result=result)
        return exit_code

    def test_exit_0_on_success(self):
        self.assertEqual(self._exit(_SUCCESS_RESULT), 0)

    def test_exit_1_on_pipeline_failure(self):
        self.assertEqual(self._exit(_FAILURE_RESULT), 1)

    def test_exit_1_on_adapter_error(self):
        result = {**_SUCCESS_RESULT, "success": False,
                  "errors": [{"code": "AUTH_ERROR", "message": "bad creds"}]}
        self.assertEqual(self._exit(result), 1)

    def test_exit_1_on_bad_json(self):
        exit_code, _, _ = _run_main("not json")
        self.assertEqual(exit_code, 1)


# ---------------------------------------------------------------------------
# TestSubprocess
# ---------------------------------------------------------------------------

class TestSubprocess(unittest.TestCase):
    """True end-to-end: spawn a real subprocess and check stdin/stdout/exit."""

    def _run(self, stdin_text: str, env_extras: dict | None = None):
        import os
        env = {**os.environ, **(env_extras or {})}
        proc = subprocess.run(
            [sys.executable, "-m", "tools.publish_pipeline"],
            input=stdin_text.encode(),
            capture_output=True,
            env=env,
            cwd="/home/user/Openclaw-Social-Tools",
        )
        try:
            output = json.loads(proc.stdout.decode())
        except json.JSONDecodeError:
            output = proc.stdout.decode()
        return proc.returncode, output

    def test_invalid_json_exits_1_subprocess(self):
        exit_code, _ = self._run("not json")
        self.assertEqual(exit_code, 1)

    def test_invalid_json_output_is_json_subprocess(self):
        _, output = self._run("not json")
        self.assertIsInstance(output, dict)

    def test_invalid_json_error_code_subprocess(self):
        _, output = self._run("not json")
        codes = [e["code"] for e in output.get("errors", [])]
        self.assertIn("INVALID_INPUT", codes)

    def test_unknown_platform_exits_1_subprocess(self):
        post = {"platform": "myspace", "content": "Hi"}
        exit_code, output = self._run(json.dumps(post))
        self.assertEqual(exit_code, 1)
        self.assertFalse(output["success"])

    def test_unknown_platform_validation_error_subprocess(self):
        post = {"platform": "myspace", "content": "Hi"}
        _, output = self._run(json.dumps(post))
        codes = [e["code"] for e in output.get("validation_errors", [])]
        self.assertIn("UNSUPPORTED_PLATFORM", codes)

    def test_missing_credentials_exits_1_subprocess(self):
        """Valid post to twitter but no credentials → adapter returns AUTH_ERROR."""
        post = {"platform": "twitter", "content": "Hello!"}
        # Strip all Twitter env vars so the adapter gets empty strings → AUTH_ERROR
        import os
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("TWITTER_")}
        proc = subprocess.run(
            [sys.executable, "-m", "tools.publish_pipeline"],
            input=json.dumps(post).encode(),
            capture_output=True,
            env=env,
            cwd="/home/user/Openclaw-Social-Tools",
        )
        self.assertEqual(proc.returncode, 1)
        output = json.loads(proc.stdout.decode())
        self.assertFalse(output["success"])

    def test_output_is_valid_json_for_valid_input_subprocess(self):
        """Even a real (failing) run produces valid JSON on stdout."""
        post = {"platform": "twitter", "content": "Hello from OpenClaw!"}
        _, output = self._run(json.dumps(post))
        self.assertIsInstance(output, dict)
        self.assertIn("success", output)

    def test_all_required_fields_present_subprocess(self):
        post = {"platform": "twitter", "content": "Hello!"}
        _, output = self._run(json.dumps(post))
        for field in ("success", "platform", "post_id", "character_count",
                      "validation_errors", "media_results", "errors", "warnings"):
            self.assertIn(field, output)


if __name__ == "__main__":
    unittest.main()

"""Tests for the publish_pipeline CLI (python -m tools.publish_pipeline).

Coverage:
  TestValidInput        — valid post JSON → publish_to_platform called,
                          result JSON on stdout, exit 0 on success / 1 on failure
  TestInvalidJson       — non-JSON stdin → structured error result, exit 1
  TestCredentials       — CLI always passes credentials=None so adapters read env
  TestOutputFormat      — stdout is valid JSON, contains all required fields
  TestExitCodes         — exit 0 on success, exit 1 on any failure path
  TestSubprocess        — end-to-end via subprocess for real stdin/stdout/exit
  TestPlatformFlag      — --platform flag injects / overrides platform
  TestLoadEnvFile       — _load_env_file parser: blank lines, comments, quotes, etc.
  TestEnvFile           — .env loading in _main: default .env, --env-file,
                          env vars win over file, missing file harmless,
                          bad --env-file path errors cleanly
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.publish_pipeline.__main__ import _load_env_file, _main

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    """Run _main() with patched stdin/stdout/argv; return (exit_code, parsed_output)."""
    target = "tools.publish_pipeline.__main__.publish_to_platform"
    captured = io.StringIO()

    ctx = patch(target, return_value=mock_result) if mock_result is not None else patch(target)

    with ctx as mock_fn, \
         patch("sys.argv", ["python -m tools.publish_pipeline"]), \
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


# ---------------------------------------------------------------------------
# TestPlatformFlag
# ---------------------------------------------------------------------------

class TestPlatformFlag(unittest.TestCase):
    """--platform flag injects or overrides the platform in the post dict."""

    def _run_with_argv(self, stdin_text: str, argv: list[str], mock_result=None):
        """Run _main() with patched sys.argv and stdin; return (exit_code, output, mock_fn)."""
        target = "tools.publish_pipeline.__main__.publish_to_platform"
        captured = io.StringIO()
        full_argv = ["python -m tools.publish_pipeline"] + argv

        ctx = patch(target, return_value=mock_result) if mock_result is not None else patch(target)

        with ctx as mock_fn, \
             patch("sys.argv", full_argv), \
             patch("sys.stdin", io.StringIO(stdin_text)), \
             patch("sys.stdout", captured):
            try:
                _main()
                exit_code = 0
            except SystemExit as exc:
                exit_code = exc.code

        captured.seek(0)
        try:
            output = json.loads(captured.read())
        except json.JSONDecodeError:
            output = None
        return exit_code, output, mock_fn

    def test_platform_flag_sets_platform_in_post(self):
        post = {"content": "Hello!"}
        _, _, mock_fn = self._run_with_argv(
            json.dumps(post), ["--platform", "twitter"], mock_result=_SUCCESS_RESULT,
        )
        called_post = mock_fn.call_args[0][0]
        self.assertEqual(called_post["platform"], "twitter")

    def test_platform_flag_overrides_json_platform(self):
        post = {"platform": "twitter", "content": "Hello!"}
        _, _, mock_fn = self._run_with_argv(
            json.dumps(post), ["--platform", "linkedin"], mock_result=_SUCCESS_RESULT,
        )
        called_post = mock_fn.call_args[0][0]
        self.assertEqual(called_post["platform"], "linkedin")

    def test_no_flag_preserves_json_platform(self):
        post = {"platform": "twitter", "content": "Hello!"}
        _, _, mock_fn = self._run_with_argv(
            json.dumps(post), [], mock_result=_SUCCESS_RESULT,
        )
        called_post = mock_fn.call_args[0][0]
        self.assertEqual(called_post["platform"], "twitter")

    def test_no_flag_no_json_platform_pipeline_still_called(self):
        """No flag and no platform in JSON — pipeline is called; it returns a validation error."""
        post = {"content": "Hello!"}
        _, _, mock_fn = self._run_with_argv(
            json.dumps(post), [], mock_result=_FAILURE_RESULT,
        )
        mock_fn.assert_called_once()

    def test_platform_flag_exit_0_on_success(self):
        post = {"content": "Hello!"}
        exit_code, _, _ = self._run_with_argv(
            json.dumps(post), ["--platform", "twitter"], mock_result=_SUCCESS_RESULT,
        )
        self.assertEqual(exit_code, 0)

    def test_platform_flag_exit_1_on_failure(self):
        post = {"content": "Hello!"}
        exit_code, _, _ = self._run_with_argv(
            json.dumps(post), ["--platform", "twitter"], mock_result=_FAILURE_RESULT,
        )
        self.assertEqual(exit_code, 1)

    def test_platform_flag_result_on_stdout(self):
        post = {"content": "Hello!"}
        _, output, _ = self._run_with_argv(
            json.dumps(post), ["--platform", "twitter"], mock_result=_SUCCESS_RESULT,
        )
        self.assertIsNotNone(output)
        self.assertTrue(output["success"])

    def test_help_flag_exits_0(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.publish_pipeline", "--help"],
            capture_output=True,
            cwd="/home/user/Openclaw-Social-Tools",
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b"--platform", proc.stdout)

    def test_subprocess_platform_flag_unsupported_platform(self):
        """--platform myspace → UNSUPPORTED_PLATFORM validation error."""
        post = {"content": "Hello!"}
        proc = subprocess.run(
            [sys.executable, "-m", "tools.publish_pipeline", "--platform", "myspace"],
            input=json.dumps(post).encode(),
            capture_output=True,
            cwd="/home/user/Openclaw-Social-Tools",
        )
        self.assertEqual(proc.returncode, 1)
        output = json.loads(proc.stdout.decode())
        codes = [e["code"] for e in output.get("validation_errors", [])]
        self.assertIn("UNSUPPORTED_PLATFORM", codes)

    def test_subprocess_platform_flag_no_json_platform(self):
        """--platform twitter, no platform in JSON → reaches adapter (AUTH_ERROR)."""
        import os
        env = {k: v for k, v in os.environ.items() if not k.startswith("TWITTER_")}
        post = {"content": "Hello from OpenClaw!"}
        proc = subprocess.run(
            [sys.executable, "-m", "tools.publish_pipeline", "--platform", "twitter"],
            input=json.dumps(post).encode(),
            capture_output=True,
            env=env,
            cwd="/home/user/Openclaw-Social-Tools",
        )
        self.assertEqual(proc.returncode, 1)
        output = json.loads(proc.stdout.decode())
        # Reached the adapter with correct platform — AUTH_ERROR, not UNSUPPORTED_PLATFORM
        self.assertEqual(output["platform"], "twitter")
        self.assertEqual(output["validation_errors"], [])
        codes = [e["code"] for e in output.get("errors", [])]
        self.assertIn("AUTH_ERROR", codes)

    def test_subprocess_platform_flag_overrides_json_platform(self):
        """--platform twitter overrides platform: myspace in JSON body."""
        import os
        env = {k: v for k, v in os.environ.items() if not k.startswith("TWITTER_")}
        post = {"platform": "myspace", "content": "Hello!"}
        proc = subprocess.run(
            [sys.executable, "-m", "tools.publish_pipeline", "--platform", "twitter"],
            input=json.dumps(post).encode(),
            capture_output=True,
            env=env,
            cwd="/home/user/Openclaw-Social-Tools",
        )
        output = json.loads(proc.stdout.decode())
        # --platform twitter wins; reaches Twitter adapter, not an UNSUPPORTED_PLATFORM error
        self.assertEqual(output["platform"], "twitter")
        self.assertEqual(output["validation_errors"], [])


# ---------------------------------------------------------------------------
# TestLoadEnvFile  (unit tests for the parser — no subprocess, no CLI)
# ---------------------------------------------------------------------------

class TestLoadEnvFile(unittest.TestCase):

    def _write(self, content: str) -> str:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".env",
                                          delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        return tmp.name

    def test_simple_key_value(self):
        path = self._write("FOO=bar\n")
        self.assertEqual(_load_env_file(path), {"FOO": "bar"})
        os.unlink(path)

    def test_blank_lines_ignored(self):
        path = self._write("\nFOO=bar\n\nBAZ=qux\n")
        self.assertIn("FOO", _load_env_file(path))
        self.assertIn("BAZ", _load_env_file(path))
        os.unlink(path)

    def test_comment_lines_ignored(self):
        path = self._write("# this is a comment\nFOO=bar\n")
        result = _load_env_file(path)
        self.assertNotIn("# this is a comment", result)
        self.assertEqual(result["FOO"], "bar")
        os.unlink(path)

    def test_double_quoted_value_unquoted(self):
        path = self._write('FOO="hello world"\n')
        self.assertEqual(_load_env_file(path)["FOO"], "hello world")
        os.unlink(path)

    def test_single_quoted_value_unquoted(self):
        path = self._write("FOO='hello world'\n")
        self.assertEqual(_load_env_file(path)["FOO"], "hello world")
        os.unlink(path)

    def test_mismatched_quotes_not_unquoted(self):
        path = self._write('FOO="hello\'\n')
        # mismatched quotes → value kept as-is
        val = _load_env_file(path)["FOO"]
        self.assertTrue(val.startswith('"'))
        os.unlink(path)

    def test_line_without_equals_skipped(self):
        path = self._write("NOEQUALS\nFOO=bar\n")
        result = _load_env_file(path)
        self.assertNotIn("NOEQUALS", result)
        self.assertEqual(result["FOO"], "bar")
        os.unlink(path)

    def test_whitespace_around_key_and_value_stripped(self):
        path = self._write("  FOO  =  bar  \n")
        self.assertEqual(_load_env_file(path)["FOO"], "bar")
        os.unlink(path)

    def test_empty_value_allowed(self):
        path = self._write("FOO=\n")
        self.assertEqual(_load_env_file(path)["FOO"], "")
        os.unlink(path)

    def test_value_with_equals_sign(self):
        path = self._write("FOO=a=b=c\n")
        self.assertEqual(_load_env_file(path)["FOO"], "a=b=c")
        os.unlink(path)

    def test_file_not_found_raises(self):
        with self.assertRaises(FileNotFoundError):
            _load_env_file("/no/such/file.env")

    def test_multiple_keys(self):
        path = self._write("A=1\nB=2\nC=3\n")
        result = _load_env_file(path)
        self.assertEqual(result, {"A": "1", "B": "2", "C": "3"})
        os.unlink(path)


# ---------------------------------------------------------------------------
# TestEnvFile  (CLI integration — .env loading in _main)
# ---------------------------------------------------------------------------

class TestEnvFile(unittest.TestCase):

    def _write_env(self, content: str) -> str:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".env",
                                          delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        return tmp.name

    def _run(self, stdin_text: str, argv: list[str], mock_result=None,
             extra_env: dict | None = None):
        target = "tools.publish_pipeline.__main__.publish_to_platform"
        captured = io.StringIO()
        full_argv = ["python -m tools.publish_pipeline"] + argv
        ctx = patch(target, return_value=mock_result) if mock_result is not None \
              else patch(target)
        env_patch = {**(extra_env or {})}

        with ctx as mock_fn, \
             patch("sys.argv", full_argv), \
             patch("sys.stdin", io.StringIO(stdin_text)), \
             patch("sys.stdout", captured), \
             patch.dict(os.environ, env_patch, clear=False):
            try:
                _main()
                exit_code = 0
            except SystemExit as exc:
                exit_code = exc.code

        captured.seek(0)
        try:
            output = json.loads(captured.read())
        except json.JSONDecodeError:
            output = None
        return exit_code, output, mock_fn

    def test_env_file_key_loaded_into_environ(self):
        path = self._write_env("TEST_CLI_KEY=loaded_from_file\n")
        post = {"platform": "twitter", "content": "Hi"}
        captured_environ = {}

        def spy_pipeline(p, **_kw):
            captured_environ.update(os.environ)
            return _SUCCESS_RESULT

        try:
            with patch("tools.publish_pipeline.__main__.publish_to_platform",
                       side_effect=spy_pipeline), \
                 patch("sys.argv", ["prog", "--env-file", path]), \
                 patch("sys.stdin", io.StringIO(json.dumps(post))), \
                 patch("sys.stdout", io.StringIO()):
                try:
                    _main()
                except SystemExit:
                    pass
            self.assertEqual(captured_environ.get("TEST_CLI_KEY"), "loaded_from_file")
        finally:
            os.unlink(path)
            os.environ.pop("TEST_CLI_KEY", None)

    def test_real_env_var_wins_over_env_file(self):
        path = self._write_env("OVERRIDE_TEST=from_file\n")
        post = {"platform": "twitter", "content": "Hi"}
        captured_environ = {}

        def spy_pipeline(p, **_kw):
            captured_environ.update(os.environ)
            return _SUCCESS_RESULT

        try:
            with patch.dict(os.environ, {"OVERRIDE_TEST": "from_real_env"}), \
                 patch("tools.publish_pipeline.__main__.publish_to_platform",
                       side_effect=spy_pipeline), \
                 patch("sys.argv", ["prog", "--env-file", path]), \
                 patch("sys.stdin", io.StringIO(json.dumps(post))), \
                 patch("sys.stdout", io.StringIO()):
                try:
                    _main()
                except SystemExit:
                    pass
            self.assertEqual(captured_environ.get("OVERRIDE_TEST"), "from_real_env")
        finally:
            os.unlink(path)
            os.environ.pop("OVERRIDE_TEST", None)

    def test_missing_default_env_is_harmless(self):
        """No .env in cwd and no --env-file → runs normally, no error."""
        post = {"platform": "twitter", "content": "Hi"}
        # Run from a temp dir with no .env present
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {k: v for k, v in os.environ.items() if not k.startswith("TWITTER_")}
            env["PYTHONPATH"] = _REPO_ROOT
            proc = subprocess.run(
                [sys.executable, "-m", "tools.publish_pipeline", "--platform", "twitter"],
                input=json.dumps(post).encode(),
                capture_output=True,
                cwd=tmpdir,
                env=env,
            )
        # No crash — exits 1 because no credentials, but output is valid JSON
        output = json.loads(proc.stdout.decode())
        self.assertIsInstance(output, dict)
        self.assertIn("success", output)

    def test_explicit_env_file_not_found_exits_1(self):
        """--env-file pointing to a non-existent file → exit 1, ENV_FILE_ERROR."""
        post = {"platform": "twitter", "content": "Hi"}
        proc = subprocess.run(
            [sys.executable, "-m", "tools.publish_pipeline",
             "--env-file", "/no/such/file.env"],
            input=json.dumps(post).encode(),
            capture_output=True,
            cwd="/home/user/Openclaw-Social-Tools",
        )
        self.assertEqual(proc.returncode, 1)
        output = json.loads(proc.stdout.decode())
        codes = [e["code"] for e in output.get("errors", [])]
        self.assertIn("ENV_FILE_ERROR", codes)

    def test_env_file_credentials_reach_adapter_subprocess(self):
        """Credentials from .env file are picked up by the adapter."""
        path = self._write_env(
            "TWITTER_API_KEY=file_key\n"
            "TWITTER_API_SECRET=file_secret\n"
            "TWITTER_ACCESS_TOKEN=file_token\n"
            "TWITTER_ACCESS_SECRET=file_token_secret\n"
        )
        post = {"content": "Hello from .env!"}
        try:
            env = {k: v for k, v in os.environ.items() if not k.startswith("TWITTER_")}
            proc = subprocess.run(
                [sys.executable, "-m", "tools.publish_pipeline",
                 "--platform", "twitter", "--env-file", path],
                input=json.dumps(post).encode(),
                capture_output=True,
                env=env,
                cwd="/home/user/Openclaw-Social-Tools",
            )
            output = json.loads(proc.stdout.decode())
            # Credentials were loaded → adapter was reached → fails at HTTP
            # (not at AUTH_ERROR due to missing creds, but at NETWORK_ERROR or similar)
            # Key assertion: no AUTH_ERROR from missing credentials
            self.assertEqual(output.get("validation_errors"), [])
            errors = output.get("errors", [])
            auth_errors = [e for e in errors if e.get("code") == "AUTH_ERROR"
                           and "Missing credentials" in e.get("message", "")]
            self.assertEqual(auth_errors, [],
                             msg="Credentials from .env file should have been loaded")
        finally:
            os.unlink(path)

    def test_env_file_malformed_lines_skipped(self):
        """Lines without '=' are silently skipped; parser does not crash."""
        path = self._write_env(
            "GOOD_KEY=good_value\n"
            "THIS_LINE_HAS_NO_EQUALS\n"
            "# comment\n"
            "\n"
            "ANOTHER_KEY=another_value\n"
        )
        result = _load_env_file(path)
        os.unlink(path)
        self.assertEqual(result.get("GOOD_KEY"), "good_value")
        self.assertEqual(result.get("ANOTHER_KEY"), "another_value")
        self.assertNotIn("THIS_LINE_HAS_NO_EQUALS", result)

    def test_default_dot_env_loaded_from_cwd_subprocess(self):
        """A .env file in the working directory is auto-loaded without --env-file."""
        post = {"content": "Hello!"}
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            with open(env_path, "w") as f:
                f.write(
                    "TWITTER_API_KEY=cwd_key\n"
                    "TWITTER_API_SECRET=cwd_secret\n"
                    "TWITTER_ACCESS_TOKEN=cwd_token\n"
                    "TWITTER_ACCESS_SECRET=cwd_token_secret\n"
                )
            env = {k: v for k, v in os.environ.items() if not k.startswith("TWITTER_")}
            env["PYTHONPATH"] = _REPO_ROOT
            proc = subprocess.run(
                [sys.executable, "-m", "tools.publish_pipeline", "--platform", "twitter"],
                input=json.dumps(post).encode(),
                capture_output=True,
                env=env,
                cwd=tmpdir,
            )
        output = json.loads(proc.stdout.decode())
        # Credentials loaded from .env → no "Missing credentials" AUTH_ERROR
        errors = output.get("errors", [])
        missing_cred_errors = [e for e in errors if e.get("code") == "AUTH_ERROR"
                               and "Missing credentials" in e.get("message", "")]
        self.assertEqual(missing_cred_errors, [],
                         msg=".env in cwd should have been auto-loaded")


if __name__ == "__main__":
    unittest.main()

"""stub — configurable StubAdapter for tests and development.

Unlike the inline _stub_adapter in publish_post (which always succeeds and has
no parameters), StubAdapter supports configurable success/failure responses,
exception simulation, and custom field values. It is the recommended adapter
for adapter-layer unit tests and integration scaffolding.

Usage:
    from tools.platform_adapters.stub import StubAdapter

    adapter = StubAdapter()                          # always succeeds
    adapter = StubAdapter(success=False,
                          error_code="RATE_LIMITED") # always fails
    adapter = StubAdapter(raise_exception=True)      # simulates network crash
"""

from .base import is_retryable, validate_adapter_result


class StubAdapter:
    """Configurable no-network adapter for tests and development.

    All parameters are keyword-only. The instance is callable: it accepts a
    queue entry dict and returns a result dict conforming to the adapter
    contract.
    """

    def __init__(
        self,
        *,
        success: bool = True,
        platform_post_id: str | None = "stub_pid",
        error_code: str = "ADAPTER_ERROR",
        message: str = "stub failure",
        raise_exception: bool = False,
        exception_message: str = "stub exception",
        platform_response: dict | None = None,
    ) -> None:
        self._success           = success
        self._platform_post_id  = platform_post_id
        self._error_code        = error_code
        self._message           = message
        self._raise_exception   = raise_exception
        self._exception_message = exception_message
        self._platform_response = platform_response

    def __call__(self, entry: dict) -> dict:
        """Return a configured result dict (or raise, if configured to do so)."""
        if self._raise_exception:
            raise RuntimeError(self._exception_message)

        if self._success:
            result: dict = {
                "success":           True,
                "platform_post_id":  self._platform_post_id,
                "platform_response": self._platform_response,
            }
        else:
            result = {
                "success":           False,
                "error_code":        self._error_code,
                "message":           self._message,
                "retryable":         is_retryable(self._error_code),
                "platform_response": self._platform_response,
            }

        validate_adapter_result(result)
        return result

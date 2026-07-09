"""
Tests that AuthClient correctly distinguishes a "fatal" server rejection
(bad account/password/version — retrying won't help) from other AuthError
cases, since the reconnect loop treats these very differently.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from guildcord.auth.auth_client import AuthClient, AuthError, FatalAuthError
from guildcord.auth import opcodes


class _FakeWriter:
    """Minimal stand-in for asyncio.StreamWriter — just needs to accept
    write()/drain()/close()/wait_closed() without a real socket."""

    def __init__(self):
        self.sent = bytearray()

    def write(self, data: bytes) -> None:
        self.sent += data

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


def _make_client_with_canned_response(response_bytes: bytes) -> AuthClient:
    client = AuthClient("dummy-host", 3724)
    reader = asyncio.StreamReader()
    reader.feed_data(response_bytes)
    reader.feed_eof()
    client._reader = reader
    client._writer = _FakeWriter()
    return client


async def _test_incorrect_password_is_fatal():
    # cmd=0x00, unused_error=0x00, result=WOW_FAIL_INCORRECT_PASSWORD
    response = bytes([0x00, 0x00, opcodes.WOW_FAIL_INCORRECT_PASSWORD])
    client = _make_client_with_canned_response(response)
    with pytest.raises(FatalAuthError):
        await client._send_logon_challenge("TESTUSER")


async def _test_unknown_account_is_fatal():
    response = bytes([0x00, 0x00, opcodes.WOW_FAIL_UNKNOWN_ACCOUNT])
    client = _make_client_with_canned_response(response)
    with pytest.raises(FatalAuthError):
        await client._send_logon_challenge("TESTUSER")


async def _test_version_invalid_is_fatal():
    response = bytes([0x00, 0x00, opcodes.WOW_FAIL_VERSION_INVALID])
    client = _make_client_with_canned_response(response)
    with pytest.raises(FatalAuthError):
        await client._send_logon_challenge("TESTUSER")


async def _test_unrecognized_failure_code_is_non_fatal():
    # Some other/unknown rejection code — not one we classify as
    # "definitely bad credentials", so it should stay a plain AuthError
    # (retryable at normal backoff) rather than FatalAuthError.
    response = bytes([0x00, 0x00, 0x0E])  # arbitrary code not in our fatal set
    client = _make_client_with_canned_response(response)
    with pytest.raises(AuthError) as exc_info:
        await client._send_logon_challenge("TESTUSER")
    assert not isinstance(exc_info.value, FatalAuthError)


async def _test_success_code_does_not_raise_before_reading_rest():
    # WOW_SUCCESS should proceed past the fatal-check without raising
    # (it'll then try to read the rest of the challenge body and fail
    # with an incomplete-read error since we didn't provide one — that's
    # expected and fine, we're only testing the fatal/non-fatal branch).
    response = bytes([0x00, 0x00, opcodes.WOW_SUCCESS])
    client = _make_client_with_canned_response(response)
    with pytest.raises(asyncio.IncompleteReadError):
        await client._send_logon_challenge("TESTUSER")


def test_incorrect_password_is_fatal():
    asyncio.run(_test_incorrect_password_is_fatal())


def test_unknown_account_is_fatal():
    asyncio.run(_test_unknown_account_is_fatal())


def test_version_invalid_is_fatal():
    asyncio.run(_test_version_invalid_is_fatal())


def test_unrecognized_failure_code_is_non_fatal():
    asyncio.run(_test_unrecognized_failure_code_is_non_fatal())


def test_success_code_does_not_raise_before_reading_rest():
    asyncio.run(_test_success_code_does_not_raise_before_reading_rest())


if __name__ == "__main__":
    test_incorrect_password_is_fatal()
    test_unknown_account_is_fatal()
    test_version_invalid_is_fatal()
    test_unrecognized_failure_code_is_non_fatal()
    test_success_code_does_not_raise_before_reading_rest()
    print("All auth error classification tests passed.")

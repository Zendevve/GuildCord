"""
Async TCP client for the WoW 3.3.5a auth server (realmd), implementing the
AuthLogonChallenge / AuthLogonProof handshake described at wowdev.wiki.

Wire packet shapes (all little-endian):

AuthLogonChallenge (client -> server):
  u8  cmd            = 0x00
  u8  error          = 0x06
  u16 size            (remaining packet length after this field)
  u8[4] gamename      = "WoW\0"
  u8  version1, version2, version3
  u16 build
  u8[4] platform      = "68x\0"   (x86, reversed/padded)
  u8[4] os            = "niW\0"   (Win, reversed/padded)
  u8[4] country       = "SUne"    (enUS, reversed/padded)
  u32 timezone_bias
  u32 ip
  u8  I_len
  u8[I_len] I          (username, uppercase)

AuthLogonChallenge (server -> client):
  u8  cmd  = 0x00
  u8  error = 0x00 (unused field, always 0)
  u8  result
  (if result == WOW_SUCCESS):
    u8[32] B
    u8  g_len
    u8[g_len] g
    u8  N_len
    u8[N_len] N
    u8[32] salt
    u8[16] unk3 (crc salt, unused by us)
    u8  security_flags

AuthLogonProof (client -> server):
  u8  cmd = 0x01
  u8[32] A
  u8[20] M1
  u8[20] crc_hash   (zeroed; we don't emulate client-file CRC checks)
  u8  number_of_keys = 0
  u8  security_flags = 0

AuthLogonProof (server -> client):
  u8  cmd = 0x01
  u8  error
  (if error == 0):
    u8[20] M2
    u32 account_flags
    u32 surveyId
    u16 unk_flags
"""

from __future__ import annotations

import asyncio
import socket
import struct
from dataclasses import dataclass

from . import opcodes, srp6


class AuthError(Exception):
    """Raised for any auth-server rejection or protocol confusion."""

    pass


class FatalAuthError(AuthError):
    """
    Raised specifically when the server explicitly rejects the account,
    password, or client version. Unlike a network blip or an unexpected
    opcode (which might be transient — server restarting, brief network
    issue), these codes mean the server looked at our credentials and
    said no. Retrying immediately with the same credentials will just
    fail again, so callers should back off much more slowly (or stop
    and alert an operator) rather than retrying at normal cadence.
    """

    pass


_FATAL_LOGON_RESULTS = {
    opcodes.WOW_FAIL_UNKNOWN_ACCOUNT,
    opcodes.WOW_FAIL_INCORRECT_PASSWORD,
    opcodes.WOW_FAIL_VERSION_INVALID,
}


@dataclass
class LoginResult:
    session_key: bytes
    username: str


class AuthClient:
    def __init__(self, host: str, port: int = 3724, platform: str = "Windows"):
        self.host = host
        self.port = port
        self.platform = platform
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port
        )

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    async def _read_exact(self, n: int) -> bytes:
        assert self._reader is not None
        return await self._reader.readexactly(n)

    def _build_logon_challenge(self, username: str) -> bytes:
        username_bytes = username.upper().encode("ascii")
        try:
            local_ip = struct.unpack(
                "!I", socket.inet_aton(socket.gethostbyname(socket.gethostname()))
            )[0]
        except Exception:
            local_ip = 0

        # Adjust platform/OS strings depending on configuration
        if self.platform.lower() == "mac":
            platform_bytes = b"Mac\0"
            os_bytes = b"xOM\0"  # OSX reversed/padded
        else:
            platform_bytes = b"68x\0"  # x86 reversed/padded
            os_bytes = b"niW\0"       # Win reversed/padded

        body = struct.pack(
            "<4sBBBH4s4s4sI I B",
            b"WoW\0",
            3, 3, 5,               # version1.version2.version3 -> 3.3.5
            opcodes.CLIENT_BUILD,
            platform_bytes,
            os_bytes,
            b"SUne",                # locale "enUS" reversed
            0,                      # timezone bias
            local_ip,
            len(username_bytes),
        ) + username_bytes

        header = struct.pack("<BBH", opcodes.CMD_AUTH_LOGON_CHALLENGE, 6, len(body))
        return header + body

    async def _send_logon_challenge(self, username: str) -> tuple[int, bytes, bytes]:
        """Returns (server_B, salt, N) — g is assumed to be the standard 7."""
        assert self._writer is not None
        self._writer.write(self._build_logon_challenge(username))
        await self._writer.drain()

        cmd = (await self._read_exact(1))[0]
        if cmd != opcodes.CMD_AUTH_LOGON_CHALLENGE:
            raise AuthError(f"unexpected opcode in challenge response: {cmd:#x}")

        _unused_error = (await self._read_exact(1))[0]
        result = (await self._read_exact(1))[0]
        if result != opcodes.WOW_SUCCESS:
            if result in _FATAL_LOGON_RESULTS:
                raise FatalAuthError(
                    f"logon challenge rejected — bad account/password/version, "
                    f"server result={result:#x}"
                )
            raise AuthError(f"logon challenge failed, server result={result:#x}")

        B_bytes = await self._read_exact(32)
        g_len = (await self._read_exact(1))[0]
        g_bytes = await self._read_exact(g_len)
        n_len = (await self._read_exact(1))[0]
        n_bytes = await self._read_exact(n_len)
        salt = await self._read_exact(32)
        _unk3 = await self._read_exact(16)
        _security_flags = await self._read_exact(1)

        server_B = int.from_bytes(B_bytes, "little")
        return server_B, salt, n_bytes

    async def _send_logon_proof(
        self, A: int, M1: bytes
    ) -> bytes:
        """Sends AuthLogonProof, returns server's M2 for verification."""
        assert self._writer is not None
        A_bytes = A.to_bytes(32, "little")
        crc_hash = b"\x00" * 20
        body = struct.pack(
            "<B32s20s20sBB",
            opcodes.CMD_AUTH_LOGON_PROOF,
            A_bytes,
            M1,
            crc_hash,
            0,  # number_of_keys
            0,  # security flags
        )
        self._writer.write(body)
        await self._writer.drain()

        cmd = (await self._read_exact(1))[0]
        if cmd != opcodes.CMD_AUTH_LOGON_PROOF:
            raise AuthError(f"unexpected opcode in proof response: {cmd:#x}")
        error = (await self._read_exact(1))[0]
        if error != opcodes.WOW_SUCCESS:
            # A proof-stage rejection means the server accepted the
            # account name but our password-derived proof didn't match
            # — i.e. wrong password. Same "won't fix itself" category
            # as the challenge-stage fatal codes.
            raise FatalAuthError(f"logon proof rejected by server, error={error:#x}")

        M2 = await self._read_exact(20)
        _account_flags = await self._read_exact(4)
        _survey_id = await self._read_exact(4)
        _unk_flags = await self._read_exact(2)
        return M2

    async def login(self, username: str, password: str) -> LoginResult:
        """
        Full SRP6 handshake: challenge -> proof -> session key.
        Raises AuthError on any protocol-level rejection, or ValueError
        if the server's proof (M2) doesn't match our own computation
        (which would indicate a MITM or a protocol mismatch, not just
        a wrong password — wrong passwords are rejected at the proof
        step by the server itself).
        """
        state = srp6.client_start(username)

        server_B, salt, _n_bytes = await self._send_logon_challenge(username)
        K, _S = srp6.client_compute_session(state, password, server_B, salt)
        M1 = srp6.compute_client_proof(username, salt, state.A, server_B, K)

        server_M2 = await self._send_logon_proof(state.A, M1)
        expected_M2 = srp6.compute_server_proof(state.A, M1, K)
        if server_M2 != expected_M2:
            raise ValueError(
                "server proof (M2) mismatch — possible MITM or protocol bug"
            )

        return LoginResult(session_key=K, username=username)

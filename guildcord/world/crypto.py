"""
World-packet header encryption for 3.3.5a.

Per wowdev.wiki ("World Packet"), every world packet header is encrypted
with a keyed RC4 stream cipher EXCEPT SMSG_AUTH_CHALLENGE and
CMSG_AUTH_SESSION. Packet *bodies* are never encrypted — only the small
header (size + opcode) is.

Two independent RC4 keystreams are derived from the SRP6 session key K
(the 40-byte key our auth handshake produced), one per direction, using
fixed seed constants and HMAC-SHA1:

    stream_key = HMAC-SHA1(seed, K)   # 20 bytes, used as the RC4 key
    RC4(stream_key), then discard (drop) the first 1024 keystream bytes
    before using it to XOR any real data.

This "drop the first 1024 bytes" step exists because RC4's keystream is
statistically biased in its earliest output — dropping it is a standard
RC4 hardening technique (also known as "RC4-drop[n]"), independently of
anything WoW-specific.

The two seeds are fixed constants embedded in the client binary. They are
directional: one seed is used by the client to decrypt server->client
headers, the other to encrypt client->server headers. Server-side, the
roles are swapped.
"""

from __future__ import annotations

import hashlib
import hmac

# Fixed seeds used to derive the two directional RC4 keystreams.
# The client uses SERVER_HEADER_KEY_SEED to decrypt SMSG headers,
# and CLIENT_HEADER_KEY_SEED to encrypt CMSG headers.
SERVER_HEADER_KEY_SEED = bytes(
    [
        0xC2, 0xB3, 0x72, 0x3C, 0xC6, 0xAE, 0xD9, 0xB5,
        0x34, 0x3C, 0x53, 0xEE, 0x2F, 0x43, 0x67, 0xCE,
    ]
)
CLIENT_HEADER_KEY_SEED = bytes(
    [
        0xCC, 0x98, 0xAE, 0x04, 0xE8, 0x97, 0xEA, 0xCA,
        0x12, 0xDD, 0xC0, 0x93, 0x42, 0x91, 0x53, 0x57,
    ]
)

RC4_DROP_BYTES = 1024


class RC4:
    """Minimal RC4 stream cipher (encrypt == decrypt, it's a XOR stream)."""

    def __init__(self, key: bytes):
        S = list(range(256))
        j = 0
        for i in range(256):
            j = (j + S[i] + key[i % len(key)]) % 256
            S[i], S[j] = S[j], S[i]
        self._S = S
        self._i = 0
        self._j = 0

    def _keystream_byte(self) -> int:
        self._i = (self._i + 1) % 256
        self._j = (self._j + self._S[self._i]) % 256
        self._S[self._i], self._S[self._j] = self._S[self._j], self._S[self._i]
        return self._S[(self._S[self._i] + self._S[self._j]) % 256]

    def crypt(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        for idx, b in enumerate(data):
            out[idx] = b ^ self._keystream_byte()
        return bytes(out)


def _derive_rc4(session_key: bytes, seed: bytes) -> RC4:
    stream_key = hmac.new(seed, session_key, hashlib.sha1).digest()
    cipher = RC4(stream_key)
    # Drop (discard) the first N keystream bytes before real use.
    cipher.crypt(bytes(RC4_DROP_BYTES))
    return cipher


class WorldCrypto:
    """
    Holds the two directional RC4 stream states for one world session.
    Call decrypt_header() on every incoming packet header (after the
    unencrypted AuthChallenge/AuthSession exchange) and encrypt_header()
    on every outgoing one, in strict packet order — RC4 is a stateful
    stream cipher, so headers MUST be processed in the exact order they
    appear on the wire.
    """

    def __init__(self, session_key: bytes):
        self._decrypt_cipher = _derive_rc4(session_key, SERVER_HEADER_KEY_SEED)
        self._encrypt_cipher = _derive_rc4(session_key, CLIENT_HEADER_KEY_SEED)

    def decrypt_header(self, header: bytes) -> bytes:
        """Decrypts an incoming SMSG header (4 bytes: size+opcode)."""
        return self._decrypt_cipher.crypt(header)

    def encrypt_header(self, header: bytes) -> bytes:
        """Encrypts an outgoing CMSG header (6 bytes: size+opcode)."""
        return self._encrypt_cipher.crypt(header)

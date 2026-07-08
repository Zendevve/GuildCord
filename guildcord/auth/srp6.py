"""
SRP6 (Secure Remote Password) implementation matching the variant used by
World of Warcraft's authentication server (build 12340 / 3.3.5a and, in
practice, essentially every version since Vanilla).

This is a clean-room implementation based on the publicly documented WoW
SRP6 parameters and flow (see wowdev.wiki "Login Packet" and general SRP6
references such as RFC 2945 for the base algorithm shape). WoW deviates
from stock SRP6 in a few ways:

  * A fixed multiplier k = 3 (rather than k = H(N, g) as in SRP-6a).
  * A non-standard "session key interleave" step used to derive the
    40-byte session key K from the raw shared secret S, rather than a
    single SHA1(S).

All integers are treated little-endian on the wire, matching WoW's packet
conventions (Blizzard packs big numbers as fixed-width little-endian byte
strings).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

# --- WoW's fixed SRP6 group parameters (256-bit N, generator g=7) ---
N = int.from_bytes(
    bytes.fromhex(
        "894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7"
    ),
    "little",
)
G = 7
K_MULTIPLIER = 3  # WoW uses fixed k=3, not SRP-6a's H(N,g)


def _sha1(*parts: bytes) -> bytes:
    h = hashlib.sha1()
    for p in parts:
        h.update(p)
    return h.digest()


def _int_to_bytes(n: int, length: int | None = None) -> bytes:
    if length is None:
        length = (n.bit_length() + 7) // 8
    return n.to_bytes(length, "little")


def _bytes_to_int(b: bytes) -> int:
    return int.from_bytes(b, "little")


def generate_salt(length: int = 32) -> bytes:
    return os.urandom(length)


def generate_private_ephemeral(length: int = 19) -> int:
    """Client's `a` or server's `b` — a random private value."""
    return _bytes_to_int(os.urandom(length))


def compute_verifier(username: str, password: str, salt: bytes) -> int:
    """
    Server-side (or account-creation-side) computation of the password
    verifier `v`, stored instead of the plaintext password.

        x = SHA1(salt | SHA1(username:password))
        v = g^x mod N
    """
    ident_hash = _sha1(f"{username.upper()}:{password.upper()}".encode("ascii"))
    x = _bytes_to_int(_sha1(salt, ident_hash))
    return pow(G, x, N)


def compute_x(username: str, password: str, salt: bytes) -> int:
    ident_hash = _sha1(f"{username.upper()}:{password.upper()}".encode("ascii"))
    return _bytes_to_int(_sha1(salt, ident_hash))


def compute_server_public(b: int, v: int) -> int:
    """B = (k*v + g^b) mod N"""
    return (K_MULTIPLIER * v + pow(G, b, N)) % N


def compute_client_public(a: int) -> int:
    """A = g^a mod N"""
    return pow(G, a, N)


def _interleave_session_key(s_bytes: bytes) -> bytes:
    """
    WoW-specific derivation of the 40-byte session key K from the raw
    shared secret S. Strips leading zero-byte pairs, splits the remaining
    bytes into even/odd interleaved halves, SHA1-hashes each half, then
    re-interleaves the two 20-byte hashes into the 40-byte key.
    """
    buf = s_bytes
    # strip leading zero bytes (S is variable length after mod N)
    start = 0
    while start < len(buf) - 1 and buf[start] == 0:
        start += 1
    buf = buf[start:]
    if len(buf) % 2 == 1:
        buf = buf[:-1]

    even = buf[0::2]
    odd = buf[1::2]

    hash_even = _sha1(even)
    hash_odd = _sha1(odd)

    interleaved = bytearray(40)
    interleaved[0::2] = hash_even
    interleaved[1::2] = hash_odd
    return bytes(interleaved)


@dataclass
class ClientSRP6State:
    username: str
    a: int
    A: int


def client_start(username: str) -> ClientSRP6State:
    a = generate_private_ephemeral()
    A = compute_client_public(a)
    return ClientSRP6State(username=username, a=a, A=A)


def client_compute_session(
    state: ClientSRP6State,
    password: str,
    server_B: int,
    salt: bytes,
) -> tuple[bytes, int]:
    """
    Given the server's public value B and salt, compute:
      - the 40-byte session key K
      - the raw shared secret S (as int), mainly useful for tests

    Steps:
      u = SHA1(A | B)
      x = SHA1(salt | SHA1(I:P))
      S = (B - k*g^x)^(a + u*x) mod N
      K = interleave(S)
    """
    A_bytes = _int_to_bytes(state.A, 32)
    B_bytes = _int_to_bytes(server_B, 32)
    u = _bytes_to_int(_sha1(A_bytes, B_bytes))

    x = compute_x(state.username, password, salt)

    base = (server_B - K_MULTIPLIER * pow(G, x, N)) % N
    exponent = state.a + u * x
    S = pow(base, exponent, N)

    S_bytes = _int_to_bytes(S, 32)
    K = _interleave_session_key(S_bytes)
    return K, S


def compute_client_proof(
    username: str,
    salt: bytes,
    A: int,
    B: int,
    K: bytes,
) -> bytes:
    """
    M1 = SHA1( (SHA1(N) XOR SHA1(g)) | SHA1(I) | s | A | B | K )
    This is the client's proof sent to the server in AuthLogonProof.
    """
    hash_n = _sha1(_int_to_bytes(N, 32))
    hash_g = _sha1(_int_to_bytes(G, 1))
    xor_ng = bytes(a ^ b for a, b in zip(hash_n, hash_g))

    hash_i = _sha1(username.upper().encode("ascii"))

    A_bytes = _int_to_bytes(A, 32)
    B_bytes = _int_to_bytes(B, 32)

    return _sha1(xor_ng, hash_i, salt, A_bytes, B_bytes, K)


def compute_server_proof(A: int, M1: bytes, K: bytes) -> bytes:
    """M2 = SHA1(A | M1 | K) — what the server should echo back."""
    A_bytes = _int_to_bytes(A, 32)
    return _sha1(A_bytes, M1, K)

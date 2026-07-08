"""
Simulates BOTH sides of the SRP6 exchange in-process to verify our client
implementation is internally consistent, without needing a live auth
server. This checks:

  1. Client and "server" derive the same session key K.
  2. The client's M1 proof matches what a real server would independently
     compute and verify.
  3. The server's M2 proof matches what the client independently verifies.

Run with: python -m pytest tests/test_srp6.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guildcord.auth import srp6


def server_side_verify_and_respond(username, password, salt, A, client_M1):
    """
    Mimics what a real auth server does: it stores only the verifier v
    (never the password), picks its own private b, computes B, and after
    receiving A/M1 from the client, derives S/K/M1 independently to check
    the client's proof, then computes M2.
    """
    v = srp6.compute_verifier(username, password, salt)
    b = srp6.generate_private_ephemeral()
    B = srp6.compute_server_public(b, v)

    A_bytes = A.to_bytes(32, "little")
    B_bytes = B.to_bytes(32, "little")
    u = int.from_bytes(srp6._sha1(A_bytes, B_bytes), "little")

    S = pow(A * pow(v, u, srp6.N), b, srp6.N)
    S_bytes = S.to_bytes((S.bit_length() + 7) // 8 or 1, "little")
    K = srp6._interleave_session_key(S_bytes)

    expected_M1 = srp6.compute_client_proof(username, salt, A, B, K)
    assert client_M1 == expected_M1, "server: client proof M1 did not match!"

    M2 = srp6.compute_server_proof(A, client_M1, K)
    return B, K, M2


def test_full_handshake_round_trip():
    username = "TESTUSER"
    password = "hunter2"

    salt = srp6.generate_salt()

    # --- client: challenge phase ---
    state = srp6.client_start(username)

    # --- server: responds with B (needs v, which needs salt+password;
    #     server would already have v stored from account creation) ---
    v = srp6.compute_verifier(username, password, salt)
    b = srp6.generate_private_ephemeral()
    B = srp6.compute_server_public(b, v)

    # --- client: computes K and M1 from server's B and salt ---
    K_client, S_client = srp6.client_compute_session(state, password, B, salt)
    M1 = srp6.compute_client_proof(username, salt, state.A, B, K_client)

    # --- server: independently verifies M1 and computes M2 ---
    A_bytes = state.A.to_bytes(32, "little")
    B_bytes = B.to_bytes(32, "little")
    u = int.from_bytes(srp6._sha1(A_bytes, B_bytes), "little")
    S_server = pow(state.A * pow(v, u, srp6.N), b, srp6.N)
    S_server_bytes = S_server.to_bytes((S_server.bit_length() + 7) // 8 or 1, "little")
    K_server = srp6._interleave_session_key(S_server_bytes)

    assert S_client == S_server, "shared secret S mismatch between client/server"
    assert K_client == K_server, "session key K mismatch between client/server"

    expected_M1 = srp6.compute_client_proof(username, salt, state.A, B, K_server)
    assert M1 == expected_M1, "client M1 proof does not verify server-side"

    M2 = srp6.compute_server_proof(state.A, M1, K_server)
    expected_M2_client_side = srp6.compute_server_proof(state.A, M1, K_client)
    assert M2 == expected_M2_client_side, "server M2 proof does not verify client-side"

    print("Session key K (hex):", K_client.hex())
    print("All SRP6 consistency checks passed.")


if __name__ == "__main__":
    test_full_handshake_round_trip()

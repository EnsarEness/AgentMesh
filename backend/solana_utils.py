"""
AgentMesh - Solana Utilities
Keypair generation and Solana devnet helpers using solders.
"""

import base64
from solders.keypair import Keypair


def generate_keypair() -> dict:
    """
    Generate a new Solana keypair.
    Returns dict with public_key (base58 str) and secret_key (base64-encoded bytes).
    """
    kp = Keypair()
    # secret() returns the 32-byte seed; to_bytes() returns the full 64-byte keypair
    secret_bytes = bytes(kp.to_bytes())
    return {
        "public_key": str(kp.pubkey()),
        "secret_key": base64.b64encode(secret_bytes).decode("ascii"),
    }


def keypair_from_bytes(encoded: str) -> Keypair:
    """Restore a Keypair from a base64-encoded byte string."""
    raw = base64.b64decode(encoded)
    return Keypair.from_bytes(raw)


if __name__ == "__main__":
    # Quick test
    result = generate_keypair()
    print(f"Public Key : {result['public_key']}")
    print(f"Secret Key : {result['secret_key'][:24]}...")

"""Anubis Proof-of-Work challenge algorithms (Argon2id and SHA-256)."""

import hashlib
import argon2.low_level


def validate_anubis_hash(h: bytes, difficulty: int) -> bool:
    """Verify that the leading `difficulty` bits of the hash `h` are 0."""
    remaining = difficulty
    for b in h:
        if remaining == 0:
            break
        if remaining >= 8:
            if b != 0:
                return False
            remaining -= 8
        else:
            mask = (0xFF << (8 - remaining)) & 0xFF
            if (b & mask) != 0:
                return False
            remaining = 0
    return True


def solve_pow(data_bytes: bytes, difficulty: int, use_le: bool) -> tuple[int, bytes]:
    """Solve Anubis Argon2id proof-of-work.

    Args:
        data_bytes: Challenge random bytes acting as the Argon2id password.
        difficulty: Number of leading 0 bits required.
        use_le: True if nonce is encoded in little-endian.

    Returns:
        A tuple of (winning_nonce, winning_hash_bytes).
    """
    nonce = 0
    while True:
        salt = nonce.to_bytes(8, "little" if use_le else "big")
        h = argon2.low_level.hash_secret_raw(
            secret=data_bytes,
            salt=salt,
            time_cost=2,
            memory_cost=19456,
            parallelism=1,
            hash_len=32,
            type=argon2.low_level.Type.ID,
            version=0x13,
        )
        if validate_anubis_hash(h, difficulty):
            return nonce, h
        nonce += 1


def solve_sha256_pow(
    random_data: str,
    difficulty: int,
    max_iterations: int = 10_000_000,
) -> tuple[int, str]:
    """Solve Anubis fast/sha256 proof-of-work.

    Computes SHA-256(random_data + str(nonce)) until the resulting hex string
    begins with `difficulty` zero characters.
    """
    target_prefix = "0" * difficulty
    nonce = 0
    while nonce < max_iterations:
        candidate = f"{random_data}{nonce}".encode("utf-8")
        h = hashlib.sha256(candidate).hexdigest()
        if h.startswith(target_prefix):
            return nonce, h
        nonce += 1
    raise RuntimeError(
        f"Anubis SHA-256 PoW could not be solved within {max_iterations} iterations"
    )

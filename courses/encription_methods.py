import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


def generate_data_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def _master_key() -> bytes:
    return bytes.fromhex(settings.VIDEO_MASTER_KEY)


def wrap_data_key(data_key: bytes) -> tuple[bytes, bytes]:
    """Encrypt the per-video data key with the server-side master key for storage at rest."""
    nonce = os.urandom(12)
    wrapped = AESGCM(_master_key()).encrypt(nonce, data_key, None)
    return wrapped, nonce


def unwrap_data_key(wrapped_data_key: bytes, nonce: bytes) -> bytes:
    return AESGCM(_master_key()).decrypt(bytes(nonce), bytes(wrapped_data_key), None)


def encrypt_file(*, source_path: str, dest_path: str, data_key: bytes) -> bytes:
    """Encrypt a video file on disk with AES-GCM. Returns the nonce used.

    # ponytail: loads whole file into memory, fine for typical course-video sizes;
    # switch to chunked/streaming AES-GCM (or age/libsodium secretstream) if files grow past ~1-2GB.
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(data_key)
    with open(source_path, "rb") as source_file:
        plaintext = source_file.read()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    with open(dest_path, "wb") as dest_file:
        dest_file.write(ciphertext)
    return nonce

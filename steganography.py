"""
steganography.py
----------------
Core LSB steganography engine.

Supports:
  • encode_text   – hide a text message inside an image
  • decode_text   – extract a hidden text message from an image
  • encode_file   – hide any file (txt/pdf/zip/…) inside an image
  • decode_file   – extract a hidden file from an image
  • calculate_capacity – report max payload size for an image

Payload format (binary, embedded in LSBs):
  [32-bit payload-length][payload bytes]

The 32-bit length header lets the decoder know exactly how many bits
to read, so no delimiter scanning is needed for robustness.

For file mode an additional human-readable metadata header is prepended
inside the payload:

  STEGO_FILE:<filename>\n<base64-encoded file bytes>###END_STEGO###

Optional AES-256-CBC encryption (via crypto_utils) is applied to the
entire payload before embedding.
"""

import os
import base64
import numpy as np
from PIL import Image

from crypto_utils import encrypt_data, decrypt_data


# ─── Internal delimiter (used inside file payloads) ───────────────────────────
FILE_DELIMITER = b"###END_STEGO###"
HEADER_PREFIX  = b"STEGO_FILE:"
HEADER_SEP     = b"\n"


# ══════════════════════════════════════════════════════════════════════════════
# Utility helpers
# ══════════════════════════════════════════════════════════════════════════════

def _open_as_rgb(image_path: str) -> Image.Image:
    """
    Open an image and ensure it is in RGB mode.
    JPEG images are converted to PNG in-memory (lossless from here on).

    Args:
        image_path: Path to the image file.

    Returns:
        PIL Image in RGB mode.

    Raises:
        FileNotFoundError: If the image does not exist.
        ValueError:        If the file is not a valid image.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    try:
        img = Image.open(image_path)
    except Exception as exc:
        raise ValueError(f"Cannot open image: {exc}") from exc

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    elif img.mode == "RGBA":
        img = img.convert("RGB")

    return img


def _bits_to_bytes(bits: list[int]) -> bytes:
    """Pack a flat list of bits (0/1 ints) into bytes."""
    result = bytearray()
    for i in range(0, len(bits), 8):
        byte_bits = bits[i:i + 8]
        if len(byte_bits) < 8:
            break
        result.append(int("".join(map(str, byte_bits)), 2))
    return bytes(result)


def _bytes_to_bits(data: bytes) -> list[int]:
    """Expand bytes into a flat list of bits (MSB first)."""
    bits = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _embed_bits(pixels: np.ndarray, bits: list[int]) -> np.ndarray:
    """
    Write `bits` into the LSB of the flattened pixel channel array.

    Args:
        pixels: numpy array of shape (H, W, 3), dtype uint8.
        bits:   List of bits to embed.

    Returns:
        Modified pixel array.
    """
    flat = pixels.flatten().astype(np.uint8)
    bit_arr = np.array(bits, dtype=np.uint8)

    if len(bit_arr) > len(flat):
        raise OverflowError(
            f"Payload ({len(bit_arr)} bits) exceeds image capacity ({len(flat)} bits)."
        )

    # Clear LSB then set new bit
    flat[: len(bit_arr)] = (flat[: len(bit_arr)] & 0xFE) | bit_arr

    return flat.reshape(pixels.shape)


def _extract_bits(pixels: np.ndarray, n_bits: int) -> list[int]:
    """
    Extract `n_bits` LSBs from the flattened pixel array.

    Args:
        pixels: numpy array (H, W, 3) uint8.
        n_bits: Number of bits to read.

    Returns:
        List of int bits.
    """
    flat = pixels.flatten()
    return list(flat[:n_bits].astype(np.uint8) & 1)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def calculate_capacity(image_path: str) -> dict:
    """
    Return the steganographic capacity of an image.

    Capacity = width × height × 3 bits  (one bit per RGB channel per pixel)
    We reserve 32 bits for the length header, leaving the rest for payload.

    Args:
        image_path: Path to the image.

    Returns:
        Dict with keys:
            capacity_bits  – total embeddable bits (excl. header)
            capacity_bytes – same in bytes
            image_size     – (width, height) tuple
            pixels         – total pixel count

    Raises:
        FileNotFoundError / ValueError on bad image.
    """
    img = _open_as_rgb(image_path)
    w, h = img.size
    total_bits = w * h * 3
    usable_bits = total_bits - 32  # subtract 32-bit length header

    return {
        "capacity_bits":  usable_bits,
        "capacity_bytes": usable_bits // 8,
        "image_size":     (w, h),
        "pixels":         w * h,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Text encode / decode
# ──────────────────────────────────────────────────────────────────────────────

def encode_text(
    image_path: str,
    message: str,
    output_path: str,
    password: str = "",
) -> dict:
    """
    Hide a UTF-8 text message inside an image using LSB steganography.

    Args:
        image_path:  Source image path (PNG or JPG).
        message:     The secret text to hide.
        output_path: Where to save the stego image (must end in .png).
        password:    Optional AES password. Empty string = no encryption.

    Returns:
        Dict with keys: output_path, payload_bytes, capacity_bytes, remaining_bytes.

    Raises:
        ValueError / OverflowError / FileNotFoundError on errors.
    """
    if not message:
        raise ValueError("Message must not be empty.")

    img     = _open_as_rgb(image_path)
    pixels  = np.array(img, dtype=np.uint8)
    cap     = calculate_capacity(image_path)

    # Build payload: raw UTF-8 bytes, then optionally encrypt
    payload: bytes = message.encode("utf-8")
    if password:
        payload = encrypt_data(payload, password)

    payload_bits = len(payload) * 8
    if payload_bits > cap["capacity_bits"]:
        raise OverflowError(
            f"Payload too large: {len(payload)} bytes needed, "
            f"but only {cap['capacity_bytes']} bytes available."
        )

    # Pack: [32-bit big-endian length][payload bits]
    length_bits = _bytes_to_bits(len(payload).to_bytes(4, "big"))
    all_bits    = length_bits + _bytes_to_bits(payload)

    modified = _embed_bits(pixels, all_bits)
    result_img = Image.fromarray(modified, "RGB")
    result_img.save(output_path, "PNG")

    return {
        "output_path":     output_path,
        "payload_bytes":   len(payload),
        "capacity_bytes":  cap["capacity_bytes"],
        "remaining_bytes": cap["capacity_bytes"] - len(payload),
    }


def decode_text(image_path: str, password: str = "") -> str:
    """
    Extract a hidden text message from a stego image.

    Args:
        image_path: Path to the stego image.
        password:   AES password (must match what was used during encode).

    Returns:
        The decoded plaintext message string.

    Raises:
        ValueError: If no valid message found or wrong password.
    """
    img    = _open_as_rgb(image_path)
    pixels = np.array(img, dtype=np.uint8)

    total_available = pixels.size  # total channel values

    # Read the 32-bit length header first
    if total_available < 32:
        raise ValueError("Image is too small to contain any hidden data.")

    length_bits  = _extract_bits(pixels, 32)
    payload_len  = int("".join(map(str, length_bits)), 2)

    # Sanity check
    if payload_len == 0 or payload_len * 8 > total_available - 32:
        raise ValueError("No valid hidden message found in this image.")

    # Read the payload bits
    payload_bits = _extract_bits(pixels, 32 + payload_len * 8)[32:]
    payload      = _bits_to_bytes(payload_bits)

    # Decrypt if password provided
    if password:
        try:
            payload = decrypt_data(payload, password)
        except Exception as exc:
            raise ValueError(str(exc)) from exc

    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        if not password:
            raise ValueError(
                "Could not decode message. "
                "The image may be encrypted — try providing a password."
            ) from exc
        raise ValueError("Decryption succeeded but result is not valid text.") from exc


# ──────────────────────────────────────────────────────────────────────────────
# File encode / decode
# ──────────────────────────────────────────────────────────────────────────────

def encode_file(
    image_path: str,
    file_path: str,
    output_path: str,
    password: str = "",
) -> dict:
    """
    Hide any file inside an image using LSB steganography.

    Internal payload format (before optional encryption):
        b"STEGO_FILE:<filename>\\n<base64 file bytes>###END_STEGO###"

    Args:
        image_path:  Source image path.
        file_path:   Path to the file to hide.
        output_path: Where to save the stego image.
        password:    Optional AES password.

    Returns:
        Dict with output_path, file_size, payload_bytes, capacity_bytes, remaining_bytes.

    Raises:
        FileNotFoundError / ValueError / OverflowError on errors.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File to hide not found: {file_path}")

    filename = os.path.basename(file_path).encode("utf-8")

    with open(file_path, "rb") as fh:
        file_bytes = fh.read()

    if not file_bytes:
        raise ValueError("The file to hide is empty.")

    # Encode file bytes as base64 so the payload is purely ASCII-safe
    b64_file = base64.b64encode(file_bytes)

    # Build internal payload
    payload: bytes = (
        HEADER_PREFIX + filename + HEADER_SEP + b64_file + FILE_DELIMITER
    )

    if password:
        payload = encrypt_data(payload, password)

    img    = _open_as_rgb(image_path)
    pixels = np.array(img, dtype=np.uint8)
    cap    = calculate_capacity(image_path)

    if len(payload) * 8 > cap["capacity_bits"]:
        raise OverflowError(
            f"File too large: encoded payload is {len(payload)} bytes, "
            f"but image capacity is only {cap['capacity_bytes']} bytes."
        )

    length_bits = _bytes_to_bits(len(payload).to_bytes(4, "big"))
    all_bits    = length_bits + _bytes_to_bits(payload)

    modified   = _embed_bits(pixels, all_bits)
    result_img = Image.fromarray(modified, "RGB")
    result_img.save(output_path, "PNG")

    return {
        "output_path":     output_path,
        "file_size":       len(file_bytes),
        "payload_bytes":   len(payload),
        "capacity_bytes":  cap["capacity_bytes"],
        "remaining_bytes": cap["capacity_bytes"] - len(payload),
    }


def decode_file(image_path: str, output_folder: str, password: str = "") -> dict:
    """
    Extract a hidden file from a stego image.

    Args:
        image_path:    Path to the stego image.
        output_folder: Directory where the recovered file will be saved.
        password:      AES password (must match encode time).

    Returns:
        Dict with: filename, output_path, file_size.

    Raises:
        ValueError:        If no valid file payload found or wrong password.
        FileNotFoundError: If image not found.
    """
    img    = _open_as_rgb(image_path)
    pixels = np.array(img, dtype=np.uint8)

    if pixels.size < 32:
        raise ValueError("Image is too small to contain any hidden data.")

    # Read length header
    length_bits = _extract_bits(pixels, 32)
    payload_len = int("".join(map(str, length_bits)), 2)

    if payload_len == 0 or payload_len * 8 > pixels.size - 32:
        raise ValueError("No valid hidden file found in this image.")

    # Read payload
    payload_bits = _extract_bits(pixels, 32 + payload_len * 8)[32:]
    payload      = _bits_to_bytes(payload_bits)

    # Decrypt if needed
    if password:
        try:
            payload = decrypt_data(payload, password)
        except Exception as exc:
            raise ValueError(str(exc)) from exc

    # Parse internal file payload
    if not payload.startswith(HEADER_PREFIX):
        raise ValueError(
            "No valid file payload found. "
            "This image may contain a text message, or the password is wrong."
        )

    # Strip the STEGO_FILE: prefix
    rest = payload[len(HEADER_PREFIX):]

    sep_idx = rest.find(HEADER_SEP)
    if sep_idx == -1:
        raise ValueError("Corrupted file payload: missing filename separator.")

    filename_bytes = rest[:sep_idx]
    remainder      = rest[sep_idx + len(HEADER_SEP):]

    delim_idx = remainder.rfind(FILE_DELIMITER)
    if delim_idx == -1:
        raise ValueError("Corrupted file payload: missing end delimiter.")

    b64_file   = remainder[:delim_idx]
    file_bytes = base64.b64decode(b64_file)

    filename = filename_bytes.decode("utf-8")

    # Sanitize filename to prevent path traversal
    filename = os.path.basename(filename)
    if not filename:
        filename = "recovered_file"

    os.makedirs(output_folder, exist_ok=True)
    out_path = os.path.join(output_folder, filename)

    with open(out_path, "wb") as fh:
        fh.write(file_bytes)

    return {
        "filename":    filename,
        "output_path": out_path,
        "file_size":   len(file_bytes),
    }

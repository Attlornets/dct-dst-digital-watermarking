"""Mid-frequency QIM watermark embedding and authenticated extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
from numpy.typing import NDArray

from .crypto_utils import (
    AuthenticationError,
    decrypt_metadata,
    encrypt_metadata,
    MIN_ENCRYPTED_SIZE,
)
from .transforms import (
    BLOCK_SIZE,
    TransformMode,
    bgr_to_ycrcb,
    complete_block_shape,
    forward_block,
    inverse_block,
    ycrcb_to_bgr,
)

MID_FREQUENCY_COORDINATES = ((2, 3), (3, 2), (4, 1), (1, 4))
HEADER_SIZE_BYTES = 4
HEADER_SIZE_BITS = HEADER_SIZE_BYTES * 8


class WatermarkError(ValueError):
    """Raised when the image cannot carry or yield a valid watermark."""


@dataclass(frozen=True)
class WatermarkResult:
    """An embedded image and the associated capacity information."""

    image: NDArray[np.uint8]
    payload_bits: int
    capacity_bits: int

    @property
    def capacity_used_percent(self) -> float:
        return 100.0 * self.payload_bits / self.capacity_bits


def _validate_alpha(alpha: float) -> None:
    if not np.isfinite(alpha) or alpha <= 0:
        raise ValueError("Embedding strength alpha must be a finite positive number.")


def _iter_coefficients(
    y_channel: NDArray[np.float32], mode: TransformMode
) -> Iterator[tuple[int, int, NDArray[np.float64], tuple[int, int]]]:
    block_rows, block_cols = y_channel.shape[0] // BLOCK_SIZE, y_channel.shape[1] // BLOCK_SIZE
    for block_row in range(block_rows):
        for block_col in range(block_cols):
            row = block_row * BLOCK_SIZE
            col = block_col * BLOCK_SIZE
            block = y_channel[row : row + BLOCK_SIZE, col : col + BLOCK_SIZE]
            yield block_row, block_col, forward_block(block, block_row, block_col, mode), (row, col)


def _capacity_bits(image_shape: tuple[int, ...]) -> int:
    height, width = image_shape[:2]
    block_rows, block_cols = height // BLOCK_SIZE, width // BLOCK_SIZE
    return block_rows * block_cols * len(MID_FREQUENCY_COORDINATES)


def _payload_to_bits(payload: bytes) -> list[int]:
    framed = len(payload).to_bytes(HEADER_SIZE_BYTES, "big") + payload
    return [int(bit) for byte in framed for bit in f"{byte:08b}"]


def _bits_to_bytes(bits: list[int]) -> bytes:
    if len(bits) % 8:
        raise WatermarkError("Extracted watermark does not contain a whole number of bytes.")
    return bytes(
        int("".join(str(bit) for bit in bits[index : index + 8]), 2)
        for index in range(0, len(bits), 8)
    )


def _qim_encode(value: float, bit: int, alpha: float) -> float:
    """Project onto the nearest alpha-spaced lattice with the requested parity."""
    nearest_index = int(np.rint((value / alpha - bit) / 2.0)) * 2 + bit
    return float(nearest_index * alpha)


def _qim_decode(value: float, alpha: float) -> int:
    return int(np.rint(value / alpha)) % 2


def embed_watermark(
    image_bgr: NDArray[np.uint8],
    owner: str,
    password: str,
    mode: TransformMode = "checkerboard",
    alpha: float = 15.0,
) -> WatermarkResult:
    """Encrypt and embed owner metadata in a BGR image's luminance coefficients."""
    _validate_alpha(alpha)
    if mode not in ("checkerboard", "hybrid"):
        raise ValueError(f"Unsupported transform mode: {mode!r}.")
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("Input must be a three-channel BGR image.")

    encrypted_payload = encrypt_metadata(owner, password)
    bits = _payload_to_bits(encrypted_payload)
    capacity_bits = _capacity_bits(image_bgr.shape)
    if len(bits) > capacity_bits:
        available_bytes = max(0, capacity_bits // 8 - HEADER_SIZE_BYTES)
        raise WatermarkError(
            f"Watermark requires {len(bits)} bits, but image capacity is "
            f"{capacity_bits} bits ({available_bytes} encrypted payload bytes maximum)."
        )

    ycrcb = bgr_to_ycrcb(image_bgr)
    y_channel = ycrcb[:, :, 0].copy()
    bit_index = 0
    for block_row, block_col, coefficients, (row, col) in _iter_coefficients(
        y_channel, mode
    ):
        for coordinate in MID_FREQUENCY_COORDINATES:
            if bit_index == len(bits):
                break
            coefficients[coordinate] = _qim_encode(
                coefficients[coordinate], bits[bit_index], alpha
            )
            bit_index += 1
        if bit_index:
            reconstructed = inverse_block(coefficients, block_row, block_col, mode)
            y_channel[row : row + BLOCK_SIZE, col : col + BLOCK_SIZE] = reconstructed
        if bit_index == len(bits):
            break

    ycrcb[:, :, 0] = y_channel
    result = ycrcb_to_bgr(ycrcb)
    return WatermarkResult(result, len(bits), capacity_bits)


def _extract_bits(
    image_bgr: NDArray[np.uint8],
    count: int,
    mode: TransformMode,
    alpha: float,
) -> list[int]:
    ycrcb = bgr_to_ycrcb(image_bgr)
    bits: list[int] = []
    for block_row, block_col, coefficients, _ in _iter_coefficients(
        ycrcb[:, :, 0], mode
    ):
        for coordinate in MID_FREQUENCY_COORDINATES:
            bits.append(_qim_decode(coefficients[coordinate], alpha))
            if len(bits) == count:
                return bits
    raise WatermarkError(
        f"Image ended before {count} watermark bits could be extracted."
    )


def extract_watermark(
    image_bgr: NDArray[np.uint8],
    password: str,
    mode: TransformMode = "checkerboard",
    alpha: float = 15.0,
) -> str:
    """Extract, authenticate, and decrypt owner metadata from a BGR image."""
    _validate_alpha(alpha)
    if mode not in ("checkerboard", "hybrid"):
        raise ValueError(f"Unsupported transform mode: {mode!r}.")
    capacity_bits = _capacity_bits(image_bgr.shape)
    if capacity_bits < HEADER_SIZE_BITS:
        raise WatermarkError("Image is too small to contain a watermark length header.")
    header = _bits_to_bytes(_extract_bits(image_bgr, HEADER_SIZE_BITS, mode, alpha))
    payload_size = int.from_bytes(header, "big")
    if payload_size < MIN_ENCRYPTED_SIZE:
        raise WatermarkError("Watermark length header is invalid or image has no watermark.")
    total_bits = (HEADER_SIZE_BYTES + payload_size) * 8
    if total_bits > capacity_bits:
        raise WatermarkError(
            "Watermark length header exceeds image capacity; image may be unwatermarked "
            "or damaged."
        )
    payload = _bits_to_bytes(_extract_bits(image_bgr, total_bits, mode, alpha)[HEADER_SIZE_BITS:])
    try:
        return decrypt_metadata(payload, password)
    except AuthenticationError:
        raise
    except ValueError as exc:
        raise WatermarkError(f"Could not decrypt watermark: {exc}") from exc

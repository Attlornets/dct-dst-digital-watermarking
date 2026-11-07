"""Round-trip, authentication, and capacity tests for image watermarking."""

import numpy as np
import pytest

from src.crypto_utils import AuthenticationError
from src.metrics import psnr, ssim
from src.transforms import BLOCK_SIZE, bgr_to_ycrcb, forward_block, inverse_block, ycrcb_to_bgr
from src.watermark import WatermarkError, embed_watermark, extract_watermark


def synthetic_image(size: int = 256) -> np.ndarray:
    """Create a deterministic, textured BGR image suitable for transform tests."""
    rng = np.random.default_rng(2026)
    y, x = np.mgrid[:size, :size]
    image = np.empty((size, size, 3), dtype=np.uint8)
    image[:, :, 0] = (0.50 * x + 0.25 * y + rng.normal(0, 8, (size, size)))
    image[:, :, 1] = (0.22 * x + 0.55 * y + rng.normal(0, 8, (size, size)))
    image[:, :, 2] = (0.45 * x + 0.35 * y + rng.normal(0, 8, (size, size)))
    return np.clip(image, 0, 255).astype(np.uint8)


@pytest.mark.parametrize("mode", ["checkerboard", "hybrid"])
def test_round_trip_and_quality(mode: str) -> None:
    cover = synthetic_image()
    owner = "Copyright © 2026 Example Studio"

    result = embed_watermark(cover, owner, "correct horse battery staple", mode)

    assert extract_watermark(
        result.image, "correct horse battery staple", mode
    ) == owner
    assert result.payload_bits <= result.capacity_bits
    assert psnr(cover, result.image) > 35
    assert ssim(cover, result.image) > 0.95


def test_wrong_password_is_rejected() -> None:
    watermarked = embed_watermark(
        synthetic_image(), "Example Studio", "right-password", "hybrid"
    )

    with pytest.raises(AuthenticationError):
        extract_watermark(watermarked.image, "wrong-password", "hybrid")


def test_payload_tampering_is_rejected() -> None:
    watermarked = embed_watermark(
        synthetic_image(), "Example Studio", "right-password", "hybrid"
    )
    ycrcb = bgr_to_ycrcb(watermarked.image)
    block_row, block_col = 0, 8
    row, col = block_row * BLOCK_SIZE, block_col * BLOCK_SIZE
    block = ycrcb[row : row + BLOCK_SIZE, col : col + BLOCK_SIZE, 0]
    coefficients = forward_block(block, block_row, block_col, "hybrid")
    coefficients[(2, 3)] += 15.0
    ycrcb[row : row + BLOCK_SIZE, col : col + BLOCK_SIZE, 0] = inverse_block(
        coefficients, block_row, block_col, "hybrid"
    )
    tampered_image = ycrcb_to_bgr(ycrcb)

    with pytest.raises(AuthenticationError):
        extract_watermark(tampered_image, "right-password", "hybrid")


def test_capacity_limit_is_reported() -> None:
    tiny_image = synthetic_image(32)

    with pytest.raises(WatermarkError, match="capacity"):
        embed_watermark(
            tiny_image,
            "A" * 100,
            "password",
            "checkerboard",
        )

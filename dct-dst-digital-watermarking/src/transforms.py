"""Orthonormal DCT/DST transforms and image/block conversion utilities."""

from __future__ import annotations

from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray
from scipy.fft import dct, dst, idct, idst

BLOCK_SIZE = 8
TransformMode = Literal["checkerboard", "hybrid"]
FloatImage = NDArray[np.float32]


def _validate_block(block: NDArray[np.floating]) -> None:
    if block.shape != (BLOCK_SIZE, BLOCK_SIZE):
        raise ValueError(f"Transform input must be an {BLOCK_SIZE}x{BLOCK_SIZE} block.")


def dct2(block: NDArray[np.floating]) -> NDArray[np.float64]:
    """Apply an orthonormal, separable 2D type-II DCT."""
    _validate_block(block)
    return dct(dct(block, type=2, norm="ortho", axis=0), type=2, norm="ortho", axis=1)


def idct2(coefficients: NDArray[np.floating]) -> NDArray[np.float64]:
    """Invert :func:`dct2`."""
    _validate_block(coefficients)
    return idct(
        idct(coefficients, type=2, norm="ortho", axis=1),
        type=2,
        norm="ortho",
        axis=0,
    )


def dst2(block: NDArray[np.floating]) -> NDArray[np.float64]:
    """Apply an orthonormal, separable 2D type-II DST."""
    _validate_block(block)
    return dst(dst(block, type=2, norm="ortho", axis=0), type=2, norm="ortho", axis=1)


def idst2(coefficients: NDArray[np.floating]) -> NDArray[np.float64]:
    """Invert :func:`dst2`."""
    _validate_block(coefficients)
    return idst(
        idst(coefficients, type=2, norm="ortho", axis=1),
        type=2,
        norm="ortho",
        axis=0,
    )


def hybrid_dct_dst(block: NDArray[np.floating]) -> NDArray[np.float64]:
    """Apply row-wise DCT followed by column-wise DST."""
    _validate_block(block)
    row_dct = dct(block, type=2, norm="ortho", axis=1)
    return dst(row_dct, type=2, norm="ortho", axis=0)


def inverse_hybrid_dct_dst(
    coefficients: NDArray[np.floating],
) -> NDArray[np.float64]:
    """Invert :func:`hybrid_dct_dst` (column IDST, then row IDCT)."""
    _validate_block(coefficients)
    column_idst = idst(coefficients, type=2, norm="ortho", axis=0)
    return idct(column_idst, type=2, norm="ortho", axis=1)


def forward_block(
    block: NDArray[np.floating], row_idx: int, col_idx: int, mode: TransformMode
) -> NDArray[np.float64]:
    """Transform one block according to its mode and global block position."""
    if mode == "hybrid":
        return hybrid_dct_dst(block)
    if mode == "checkerboard":
        return dct2(block) if (row_idx + col_idx) % 2 == 0 else dst2(block)
    raise ValueError(f"Unsupported transform mode: {mode!r}.")


def inverse_block(
    coefficients: NDArray[np.floating],
    row_idx: int,
    col_idx: int,
    mode: TransformMode,
) -> NDArray[np.float64]:
    """Invert the transform selected by :func:`forward_block`."""
    if mode == "hybrid":
        return inverse_hybrid_dct_dst(coefficients)
    if mode == "checkerboard":
        return (
            idct2(coefficients)
            if (row_idx + col_idx) % 2 == 0
            else idst2(coefficients)
        )
    raise ValueError(f"Unsupported transform mode: {mode!r}.")


def bgr_to_ycrcb(image: NDArray[np.uint8]) -> FloatImage:
    """Convert an 8-bit OpenCV BGR image to float32 YCrCb channel values."""
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("Image must be a uint8 BGR array with shape (height, width, 3).")
    return cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb).astype(np.float32)


def ycrcb_to_bgr(ycrcb: NDArray[np.floating]) -> NDArray[np.uint8]:
    """Convert float32 YCrCb values to an 8-bit BGR image."""
    if ycrcb.ndim != 3 or ycrcb.shape[2] != 3:
        raise ValueError("YCrCb image must have shape (height, width, 3).")
    clipped = np.clip(np.rint(ycrcb), 0, 255).astype(np.uint8)
    return cv2.cvtColor(clipped, cv2.COLOR_YCrCb2BGR)


def complete_block_shape(height: int, width: int) -> tuple[int, int]:
    """Return the largest height/width covered by complete 8x8 blocks."""
    return height - height % BLOCK_SIZE, width - width % BLOCK_SIZE

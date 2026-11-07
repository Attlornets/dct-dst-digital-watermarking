"""Image-quality metrics and frequency-spectrum visualization helpers."""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


def _validate_pair(
    original: NDArray[np.uint8], comparison: NDArray[np.uint8]
) -> None:
    if original.shape != comparison.shape:
        raise ValueError("Images must have identical dimensions for comparison.")
    if original.dtype != np.uint8 or comparison.dtype != np.uint8:
        raise ValueError("Metric inputs must be uint8 images.")
    if original.ndim not in (2, 3):
        raise ValueError("Metric inputs must be grayscale or color images.")


def psnr(original: NDArray[np.uint8], comparison: NDArray[np.uint8]) -> float:
    """Return peak signal-to-noise ratio in dB for 8-bit images."""
    _validate_pair(original, comparison)
    return float(peak_signal_noise_ratio(original, comparison, data_range=255))


def ssim(original: NDArray[np.uint8], comparison: NDArray[np.uint8]) -> float:
    """Return structural similarity for 8-bit grayscale or color images."""
    _validate_pair(original, comparison)
    return float(
        structural_similarity(
            original,
            comparison,
            data_range=255,
            channel_axis=-1 if original.ndim == 3 else None,
        )
    )


def frequency_spectrum(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Return a display-ready log-magnitude spectrum of an image's luminance."""
    if image.dtype != np.uint8 or image.ndim not in (2, 3):
        raise ValueError("Spectrum input must be a uint8 grayscale or color image.")
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    spectrum = np.fft.fftshift(np.fft.fft2(gray.astype(np.float32)))
    magnitude = 20 * np.log1p(np.abs(spectrum))
    normalized = cv2.normalize(magnitude, None, 0, 255, cv2.NORM_MINMAX)
    return normalized.astype(np.uint8)

"""AES-authenticated dual-transform image watermarking."""

from .watermark import (
    AuthenticationError,
    WatermarkError,
    WatermarkResult,
    embed_watermark,
    extract_watermark,
)

__all__ = [
    "AuthenticationError",
    "WatermarkError",
    "WatermarkResult",
    "embed_watermark",
    "extract_watermark",
]

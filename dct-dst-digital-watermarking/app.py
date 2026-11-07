"""FastAPI application for interactive frequency-domain watermarking."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Annotated, cast

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from numpy.typing import NDArray

from src.crypto_utils import AuthenticationError
from src.metrics import frequency_spectrum, psnr, ssim
from src.transforms import BLOCK_SIZE, TransformMode, bgr_to_ycrcb, forward_block
from src.watermark import (
    MID_FREQUENCY_COORDINATES,
    WatermarkError,
    embed_watermark,
    extract_watermark,
)

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 8_000_000
ImageArray = NDArray[np.uint8]

app = FastAPI(
    title="DCT-DST Watermark Studio",
    description="Local AES-GCM-authenticated frequency-domain image watermarking.",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the single-page frontend."""
    return FileResponse(FRONTEND_DIR / "index.html")


async def _decode_upload(
    upload: UploadFile,
    allowed_suffixes: tuple[str, ...],
) -> tuple[ImageArray, ImageArray | None]:
    """Read and validate an uploaded BGR/BGRA image."""
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed_suffixes:
        expected = ", ".join(allowed_suffixes)
        raise HTTPException(
            status_code=415, detail=f"Image filename must use one of: {expected}."
        )
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image upload exceeds 25 MiB.")
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    if suffix == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="File extension does not match PNG data.")
    if suffix in (".jpg", ".jpeg") and not data.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="File extension does not match JPEG data.")
    encoded = np.frombuffer(data, dtype=np.uint8)
    decoded = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if decoded is None:
        raise HTTPException(status_code=400, detail="Could not decode uploaded image.")
    if (
        decoded.dtype != np.uint8
        or decoded.ndim != 3
        or decoded.shape[2] not in (3, 4)
    ):
        raise HTTPException(
            status_code=400, detail="Image must be an 8-bit BGR or BGRA image."
        )
    height, width = decoded.shape[:2]
    if height * width > MAX_IMAGE_PIXELS:
        raise HTTPException(status_code=413, detail="Image exceeds 8 megapixels.")
    bgr = np.ascontiguousarray(decoded[:, :, :3])
    alpha = np.ascontiguousarray(decoded[:, :, 3]) if decoded.shape[2] == 4 else None
    return bgr, alpha


def _png_bytes(image: ImageArray) -> bytes:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise HTTPException(status_code=500, detail="Could not encode PNG output.")
    return encoded.tobytes()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _rgba_image(bgr: ImageArray, alpha: ImageArray | None) -> ImageArray:
    if alpha is None:
        return bgr
    return cv2.merge((*cv2.split(bgr), alpha))


def _rounded_matrix(matrix: NDArray[np.floating]) -> list[list[float]]:
    return np.round(matrix.astype(np.float64), 3).tolist()


def _block_telemetry(
    original_bgr: ImageArray,
    watermarked_bgr: ImageArray,
    block_x: int,
    block_y: int,
    mode: TransformMode,
) -> dict[str, object]:
    """Return inspectable spatial, color, and transform data for one block."""
    height, width = original_bgr.shape[:2]
    columns, rows = width // BLOCK_SIZE, height // BLOCK_SIZE
    if not (0 <= block_x < columns and 0 <= block_y < rows):
        raise HTTPException(status_code=400, detail="Selected block is outside the image.")

    x, y = block_x * BLOCK_SIZE, block_y * BLOCK_SIZE
    original_rgb = cv2.cvtColor(
        original_bgr[y : y + BLOCK_SIZE, x : x + BLOCK_SIZE], cv2.COLOR_BGR2RGB
    )
    watermarked_rgb = cv2.cvtColor(
        watermarked_bgr[y : y + BLOCK_SIZE, x : x + BLOCK_SIZE],
        cv2.COLOR_BGR2RGB,
    )
    original_ycrcb = bgr_to_ycrcb(
        original_bgr[y : y + BLOCK_SIZE, x : x + BLOCK_SIZE]
    )
    watermarked_ycrcb = bgr_to_ycrcb(
        watermarked_bgr[y : y + BLOCK_SIZE, x : x + BLOCK_SIZE]
    )
    spatial = original_ycrcb[:, :, 0]
    original_coefficients = forward_block(spatial, block_y, block_x, mode)
    modified_coefficients = forward_block(
        watermarked_ycrcb[:, :, 0], block_y, block_x, mode
    )
    return {
        "block_x": block_x,
        "block_y": block_y,
        "mode": mode,
        "transform": (
            "DCT-II"
            if mode == "checkerboard" and (block_x + block_y) % 2 == 0
            else "DST-II"
            if mode == "checkerboard"
            else "row DCT-II → column DST-II"
        ),
        "spatial_y": _rounded_matrix(spatial),
        "reconstructed_y": _rounded_matrix(watermarked_ycrcb[:, :, 0]),
        "coefficients": _rounded_matrix(original_coefficients),
        "modified_qim": _rounded_matrix(modified_coefficients),
        "original_rgb": original_rgb.tolist(),
        "watermarked_rgb": watermarked_rgb.tolist(),
        "original_ycrcb": _rounded_matrix(original_ycrcb),
        "watermarked_ycrcb": _rounded_matrix(watermarked_ycrcb),
        "qim_coordinates": [list(point) for point in MID_FREQUENCY_COORDINATES],
    }


def _first_eligible_block(
    image_shape: tuple[int, ...], alpha_channel: ImageArray | None
) -> tuple[int, int]:
    if alpha_channel is None:
        return 0, 0
    block_rows = image_shape[0] // BLOCK_SIZE
    block_cols = image_shape[1] // BLOCK_SIZE
    for block_y in range(block_rows):
        for block_x in range(block_cols):
            alpha_block = alpha_channel[
                block_y * BLOCK_SIZE : (block_y + 1) * BLOCK_SIZE,
                block_x * BLOCK_SIZE : (block_x + 1) * BLOCK_SIZE,
            ]
            if np.all(alpha_block == 255):
                return block_x, block_y
    raise WatermarkError("Image has no fully opaque 8x8 blocks for watermarking.")


def _validate_mode(mode: str) -> TransformMode:
    if mode not in ("checkerboard", "hybrid"):
        raise HTTPException(
            status_code=422, detail="Mode must be 'checkerboard' or 'hybrid'."
        )
    return cast(TransformMode, mode)


@app.post("/api/embed")
async def api_embed(
    image: Annotated[UploadFile, File(description="PNG or JPEG cover image")],
    owner: Annotated[str, Form(min_length=1, max_length=256)],
    password: Annotated[str, Form(min_length=1, max_length=1024)],
    mode: Annotated[str, Form()] = "checkerboard",
    alpha: Annotated[float, Form()] = 15.0,
) -> dict[str, object]:
    """Encrypt ownership metadata, embed it, and return preview/inspection data."""
    selected_mode = _validate_mode(mode)
    original_bgr, alpha_channel = await _decode_upload(
        image, (".png", ".jpg", ".jpeg")
    )
    try:
        result = embed_watermark(
            original_bgr,
            owner,
            password,
            selected_mode,
            alpha,
            alpha_channel,
        )
    except (ValueError, WatermarkError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    original_png = _png_bytes(_rgba_image(original_bgr, alpha_channel))
    watermarked_png = _png_bytes(_rgba_image(result.image, alpha_channel))
    original_y = bgr_to_ycrcb(original_bgr)[:, :, 0]
    watermarked_y = bgr_to_ycrcb(result.image)[:, :, 0]
    residual = np.clip(np.abs(watermarked_y - original_y) * 20.0, 0, 255)
    if alpha_channel is not None:
        residual[alpha_channel != 255] = 0
    residual_gray = np.rint(residual).astype(np.uint8)
    residual_heatmap = cv2.applyColorMap(residual_gray, cv2.COLORMAP_INFERNO)
    spectrum = frequency_spectrum(result.image)

    sample_x, sample_y = _first_eligible_block(original_bgr.shape, alpha_channel)
    telemetry = _block_telemetry(
        original_bgr, result.image, sample_x, sample_y, selected_mode
    )
    return {
        "original_png": _b64(original_png),
        "watermarked_png": _b64(watermarked_png),
        "residual_diff_map": _b64(_png_bytes(residual_heatmap)),
        "spectrum_png": _b64(_png_bytes(spectrum)),
        "psnr": psnr(original_bgr, result.image),
        "ssim": ssim(original_bgr, result.image),
        "capacity_bits": result.capacity_bits,
        "used_bits": result.payload_bits,
        "capacity_used_percent": result.capacity_used_percent,
        "crypto": {
            "algorithm": "AES-256-GCM",
            "key_derivation": "PBKDF2-HMAC-SHA256",
            "authenticated": True,
            "salt_bytes": 16,
            "nonce_bytes": 12,
            "salt_hex": result.salt_hex,
            "nonce_hex": result.nonce_hex,
        },
        "telemetry": telemetry,
    }


@app.post("/api/verify")
async def api_verify(
    image: Annotated[UploadFile, File(description="Watermarked PNG image")],
    password: Annotated[str, Form(min_length=1, max_length=1024)],
    mode: Annotated[str, Form()] = "checkerboard",
    alpha: Annotated[float, Form()] = 15.0,
) -> dict[str, str | bool]:
    """Extract the owner and report AES-GCM authentication failures cleanly."""
    selected_mode = _validate_mode(mode)
    image_bgr, alpha_channel = await _decode_upload(image, (".png",))
    try:
        owner = extract_watermark(
            image_bgr, password, selected_mode, alpha, alpha_channel
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (ValueError, WatermarkError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"owner": owner, "authenticated": True}


@app.post("/api/inspect")
async def api_inspect(
    original: Annotated[UploadFile, File()],
    watermarked: Annotated[UploadFile, File()],
    block_x: Annotated[int, Form(ge=0)],
    block_y: Annotated[int, Form(ge=0)],
    mode: Annotated[str, Form()] = "checkerboard",
) -> dict[str, object]:
    """Return detailed color and transform data for a selected 8x8 block."""
    selected_mode = _validate_mode(mode)
    original_bgr, original_alpha = await _decode_upload(original, (".png",))
    watermarked_bgr, watermarked_alpha = await _decode_upload(watermarked, (".png",))
    if original_bgr.shape != watermarked_bgr.shape:
        raise HTTPException(status_code=400, detail="Images must have matching dimensions.")
    if (original_alpha is None) != (watermarked_alpha is None):
        raise HTTPException(status_code=400, detail="Images must have matching alpha channels.")
    return _block_telemetry(
        original_bgr, watermarked_bgr, block_x, block_y, selected_mode
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    """Provide a small local-server readiness check."""
    return {"status": "ok"}

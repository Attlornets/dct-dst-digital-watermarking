"""HTTP API tests for embedding, inspection, and authentication."""

import base64

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def cover_png() -> bytes:
    """Build a transparent image with sufficient fully opaque blocks."""
    rng = np.random.default_rng(77)
    image = rng.integers(0, 256, (128, 128, 3), dtype=np.uint8)
    alpha = np.full((128, 128), 255, dtype=np.uint8)
    alpha[:16, :16] = 0
    success, encoded = cv2.imencode(".png", cv2.merge((*cv2.split(image), alpha)))
    assert success
    return encoded.tobytes()


def test_embed_inspect_and_verify_api_round_trip() -> None:
    response = client.post(
        "/api/embed",
        files={"image": ("cover.png", cover_png(), "image/png")},
        data={
            "owner": "Example Studio",
            "password": "api-test-password",
            "mode": "hybrid",
            "alpha": "15",
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["capacity_bits"] == 1008
    assert result["used_bits"] > 0
    assert result["psnr"] > 35
    assert result["ssim"] > 0.95
    assert result["crypto"]["algorithm"] == "AES-256-GCM"
    assert len(result["crypto"]["salt_hex"]) == 32
    assert len(result["crypto"]["nonce_hex"]) == 24
    assert result["telemetry"]["spatial_y"] and len(result["telemetry"]["spatial_y"]) == 8
    assert len(base64.b64decode(result["residual_diff_map"])) > 0

    original_png = base64.b64decode(result["original_png"])
    watermarked_png = base64.b64decode(result["watermarked_png"])
    inspected = client.post(
        "/api/inspect",
        files={
            "original": ("original.png", original_png, "image/png"),
            "watermarked": ("watermarked.png", watermarked_png, "image/png"),
        },
        data={"block_x": "5", "block_y": "5", "mode": "hybrid"},
    )
    assert inspected.status_code == 200
    telemetry = inspected.json()
    assert telemetry["block_x"] == 5
    assert len(telemetry["original_rgb"]) == 8
    assert len(telemetry["modified_qim"]) == 8

    verified = client.post(
        "/api/verify",
        files={"image": ("watermarked.png", watermarked_png, "image/png")},
        data={"password": "api-test-password", "mode": "hybrid", "alpha": "15"},
    )
    assert verified.status_code == 200
    assert verified.json() == {"owner": "Example Studio", "authenticated": True}

    rejected = client.post(
        "/api/verify",
        files={"image": ("watermarked.png", watermarked_png, "image/png")},
        data={"password": "wrong-password", "mode": "hybrid", "alpha": "15"},
    )
    assert rejected.status_code == 401
    assert "authentication failed" in rejected.json()["detail"].lower()


def test_health_and_frontend_routes() -> None:
    assert client.get("/api/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Transform observatory" in page.text
    assert client.get("/static/app.js").status_code == 200

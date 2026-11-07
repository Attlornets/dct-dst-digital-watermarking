"""Command-line interface for embedding and verifying encrypted watermarks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

from src.metrics import psnr, ssim
from src.watermark import AuthenticationError, WatermarkError, embed_watermark, extract_watermark
from src.transforms import TransformMode


def _read_image(path: str) -> cv2.Mat:
    image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    if image.ndim != 3 or image.shape[2] not in (3, 4) or image.dtype.name != "uint8":
        raise ValueError("Input must be an 8-bit BGR or BGRA color image.")
    return image


def _bgr_channels(image: cv2.Mat) -> cv2.Mat:
    """Return BGR channels while keeping any alpha channel separate."""
    return image[:, :, :3]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Embed or verify an AES-GCM-authenticated frequency-domain watermark."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    embed = subparsers.add_parser("embed", help="Encrypt and embed owner metadata.")
    embed.add_argument("--input", required=True, help="Input image (BGR color image).")
    embed.add_argument("--output", required=True, help="Output lossless .png file.")
    embed.add_argument("--owner", required=True, help="Copyright/ownership metadata.")
    embed.add_argument("--password", required=True, help="Watermark encryption password.")
    embed.add_argument(
        "--mode", choices=("checkerboard", "hybrid"), default="checkerboard"
    )
    embed.add_argument("--alpha", type=float, default=15.0)

    verify = subparsers.add_parser("verify", help="Extract and authenticate a watermark.")
    verify.add_argument("--input", required=True, help="Watermarked PNG image.")
    verify.add_argument("--password", required=True, help="Watermark encryption password.")
    verify.add_argument(
        "--mode", choices=("checkerboard", "hybrid"), default="checkerboard"
    )
    verify.add_argument("--alpha", type=float, default=15.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        image = _read_image(args.input)
        bgr_image = _bgr_channels(image)
        alpha_channel = image[:, :, 3] if image.shape[2] == 4 else None
        if args.command == "embed":
            output_path = Path(args.output)
            if output_path.suffix.lower() != ".png":
                raise ValueError("Watermarked output must use the lossless .png format.")
            result = embed_watermark(
                bgr_image,
                args.owner,
                args.password,
                args.mode,
                args.alpha,
                alpha_channel,
            )
            output_image = (
                cv2.merge((*cv2.split(result.image), alpha_channel))
                if alpha_channel is not None
                else result.image
            )
            if not cv2.imwrite(str(output_path), output_image):
                raise OSError(f"Could not write output image: {output_path}")
            print(f"Watermark embedded: {output_path}")
            print(
                f"Capacity: {result.payload_bits}/{result.capacity_bits} bits "
                f"({result.capacity_used_percent:.2f}%)"
            )
            print(f"PSNR: {psnr(bgr_image, result.image):.2f} dB")
            print(f"SSIM: {ssim(bgr_image, result.image):.6f}")
            return 0

        owner = extract_watermark(
            bgr_image, args.password, args.mode, args.alpha, alpha_channel
        )
        print(f"Verified owner: {owner}")
        return 0
    except AuthenticationError as exc:
        print(f"Authentication failure: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, WatermarkError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

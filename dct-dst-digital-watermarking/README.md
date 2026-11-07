# AES-Encrypted DCT-DST Digital Watermarking

A modular Python demonstration of authenticated ownership metadata carried in
mid-frequency image coefficients. Metadata is encrypted with AES-256-GCM and
embedded in the luminance plane using Quantization Index Modulation (QIM).
The implementation supports checkerboard DCT/DST and hybrid row-DCT/column-DST
transform modes and reports PSNR and SSIM.

> This is a signal-processing demonstration, not a legal proof of ownership.
> Lossless PNG is required for verification; lossy re-encoding, resizing,
> cropping, or other image edits can destroy the watermark.

## Features

- AES-256-GCM authenticated encryption and PBKDF2-HMAC-SHA256 key derivation.
- Orthonormal 8x8 DCT, DST, and hybrid transforms.
- Luminance-only embedding in a configurable-strength QIM scheme.
- A 32-bit payload-length prefix, followed by the encrypted binary payload.
- Capacity checks, wrong-password/tampering detection, PSNR, SSIM, and a
  display-ready log-magnitude spectrum helper.

## Project layout

```text
dct-dst-digital-watermarking/
├── src/
│   ├── crypto_utils.py
│   ├── transforms.py
│   ├── watermark.py
│   └── metrics.py
├── tests/
├── samples/
├── cli.py
├── requirements.txt
└── README.md
```

## Transform and embedding model

An image is loaded as 8-bit BGR and converted to OpenCV YCrCb. Only the `Y`
(luminance) plane is modified; `Cr` and `Cb` are carried through unchanged.
The plane is traversed in non-overlapping 8x8 blocks. Incomplete right/bottom
edge strips are preserved and do not contribute capacity.

For a block `X`, the 2D transforms are separable orthonormal type-II transforms:

`C = DCT-II_rows(DCT-II_columns(X))`

`S = DST-II_rows(DST-II_columns(X))`

The checkerboard mode uses `C` when `(block_row + block_col) mod 2 = 0` and
`S` otherwise. Hybrid mode applies DCT-II across each row and then DST-II down
each column; the inverse reverses the order using IDST and then IDCT.

The coordinates `(2,3)`, `(3,2)`, `(4,1)`, and `(1,4)` are used in each block.
They exclude the DC coefficient `(0,0)` and the high-frequency bottom-right
region. A bit `b` is encoded by projecting coefficient `c` to the nearest
`alpha * k` where `k` has parity `b`:

`k = 2 * round((c / alpha - b) / 2) + b`, `c' = alpha * k`

Extraction rounds `c'/alpha` to the nearest integer and reads its parity.
Each complete block therefore carries four bits. The 32-bit big-endian byte
length prefix adds framing overhead.

## Cryptographic payload

The owner string is encoded as UTF-8 and encrypted using AES-GCM. A fresh
16-byte random salt and 12-byte nonce are stored alongside the AES-GCM output:

`salt (16) || nonce (12) || ciphertext || authentication tag (16)`

PBKDF2-HMAC-SHA256 derives a 256-bit key using 600,000 iterations. AES-GCM
authenticates the encrypted payload; it does not authenticate every pixel in
the image or establish that a claimant legally owns the image.

## Setup

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## CLI

Embed metadata and save as lossless PNG:

```powershell
python cli.py embed --input samples\cover.png --output samples\watermarked.png --owner "Example Studio" --password "choose-a-strong-password" --mode checkerboard --alpha 15
```

Verify and print the authenticated owner:

```powershell
python cli.py verify --input samples\watermarked.png --password "choose-a-strong-password" --mode checkerboard --alpha 15
```

`--mode` may be `checkerboard` or `hybrid`; the verification mode and `--alpha`
must match the embedding settings. The CLI reports capacity used, PSNR, and
SSIM after embedding. Use secrets that are not reused elsewhere. In production,
avoid putting passwords directly in shell history and use a managed secret
input mechanism.

## Capacity and output behavior

For an image of height `H` and width `W`, capacity is
`4 * floor(H/8) * floor(W/8)` bits. The framed encrypted payload requires
`8 * (4 + payload_byte_count)` bits. Oversized payloads raise a clear capacity
error. The CLI writes PNG only; use the same transform mode and alpha at
verification. Reconstructed luminance is clipped to `[0,255]`, while chroma is
not altered by the embedding process.

## Quality metrics

PSNR is measured in dB over the complete BGR image with an 8-bit data range.
SSIM uses the same image pair and data range. `frequency_spectrum` returns a
normalized, log-magnitude 2D Fourier spectrum suitable for display or saving
with OpenCV.

## Tests

```powershell
python -m pytest
```

The tests cover encrypted round trips in both transform modes, image quality,
wrong-password rejection, and capacity-limit handling.

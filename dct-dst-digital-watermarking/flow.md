# Code Flow

This guide follows the data through the project for both embedding and
verification.

## Embed: owner text to watermarked PNG

Run the CLI from the project directory:

```powershell
python cli.py embed --input samples\cover.png --output samples\watermarked.png --owner "Example Studio" --password "choose-a-password" --mode checkerboard --alpha 15
```

The flow is:

1. **Parse options** — `cli.py` reads the input/output paths, owner string,
   password, transform mode, and QIM strength.
2. **Load cover image** — OpenCV reads a three-channel BGR or four-channel BGRA
   image. For BGRA PNGs, the CLI separates and later restores the alpha channel.
3. **Encrypt metadata** — `encrypt_metadata` in `src/crypto_utils.py` derives a
   key from the password and a random salt, then returns
   `salt || nonce || ciphertext || authentication tag`.
4. **Frame the data** — `src/watermark.py` prepends a 32-bit big-endian payload
   byte length and converts all bytes into bits, most-significant bit first.
5. **Check capacity** — The payload plus header must fit four coefficient bits
   per eligible complete 8x8 block. In transparent PNGs, a block is eligible
   only when all 64 alpha values are fully opaque. If the payload does not fit,
   embedding stops with a capacity error.
6. **Convert to luminance** — `src/transforms.py` converts BGR to float32 YCrCb.
   The algorithm edits a copy of the Y channel.
7. **Transform eligible blocks** — Opaque images use every complete block.
   Transparent images skip transparent/partially transparent blocks.
   `checkerboard` chooses DCT or DST by the block coordinates; `hybrid` uses
   row-DCT followed by column-DST.
8. **Embed bits** — The next bits are placed in `(2,3)`, `(3,2)`, `(4,1)`, and
   `(1,4)` using QIM with the supplied alpha. DC and bottom-right high-frequency
   coefficients are not selected.
9. **Reconstruct** — Each changed block is inverse-transformed and written into
   the Y plane. Y is clipped/rounded for conversion back to BGR; Cr and Cb
   remain unedited by the embedding step.
10. **Save and report** — `cli.py` saves PNG, restoring the original alpha
    channel when present, and prints payload/capacity, PSNR, and SSIM. Quality
    metrics compare BGR channels only.

## Verify: watermarked PNG to owner text

```powershell
python cli.py verify --input samples\watermarked.png --password "choose-a-password" --mode checkerboard --alpha 15
```

The flow is:

1. **Load the watermarked image** as BGR or BGRA and separate alpha if present.
2. **Convert to luminance** using the same BGR-to-YCrCb conversion.
3. **Read the framing header** — The verifier chooses blocks using the same
   alpha-based rule as embedding, applies the selected transforms in order, and
   QIM-decodes the first 32 bits.
4. **Validate length** — It checks the payload size against the minimum AES-GCM
   representation and the available image capacity.
5. **Read the complete payload** — It extracts the specified number of bits
   from the same coefficient coordinates and reconstructs bytes.
6. **Authenticate/decrypt** — `decrypt_metadata` extracts salt and nonce,
   derives the key from the supplied password, and asks AES-GCM to authenticate
   and decrypt. A wrong password or altered encrypted payload produces an
   authentication failure.
7. **Display result** — On success, the CLI prints the verified owner string.

The verify command must use the **same `--mode` and `--alpha` values** as
embedding. Use a lossless PNG; JPEG recompression or other image changes may
alter coefficients and make extraction fail.

## Important functions

| Function | Module | Responsibility |
|---|---|---|
| `encrypt_metadata` / `decrypt_metadata` | `src/crypto_utils.py` | AES-GCM encryption and authenticated decryption |
| `forward_block` / `inverse_block` | `src/transforms.py` | Select the correct transform based on mode and block position |
| `embed_watermark` | `src/watermark.py` | Encrypt, frame, capacity-check, and embed payload |
| `extract_watermark` | `src/watermark.py` | Extract framing and payload, then authenticate/decrypt |
| `psnr` / `ssim` | `src/metrics.py` | Compare original and output image quality |
| `frequency_spectrum` | `src/metrics.py` | Create a display-ready Fourier magnitude spectrum |
| `main` | `cli.py` | Connect command-line arguments to image processing functions |

## Running tests

From the project directory:

```powershell
python -m pytest -q
```

The tests exercise both transform modes, owner-text recovery, PSNR/SSIM
thresholds, wrong-password rejection, payload tampering, and capacity errors.

# Design Decisions

This note explains the main implementation choices in the watermarking
project and the trade-offs they introduce.

## 1. Encrypt ownership metadata before embedding

The owner string is UTF-8 encoded and encrypted with AES-256-GCM in
[`src/crypto_utils.py`](./src/crypto_utils.py). A random 16-byte salt is used
with PBKDF2-HMAC-SHA256 (600,000 iterations) to derive a 256-bit key. Each
encryption also uses a random 12-byte nonce.

The payload layout is:

```text
salt (16 bytes) || nonce (12 bytes) || ciphertext || GCM tag (16 bytes)
```

AES-GCM provides confidentiality and detects changes to the encrypted
metadata. A wrong password or modified encrypted payload fails authentication.
It does **not** authenticate every pixel in the image or prove legal ownership.

## 2. Embed in luminance, not chroma

OpenCV loads images as BGR. The CLI also accepts BGRA PNGs, separates their
alpha channel, and restores it unchanged on save. The watermarking implementation
converts BGR to YCrCb `float32` and embeds only in the Y (luminance) channel. Cr
and Cb are carried through without intentional modification. This limits color
shifts while keeping the embedding in a spatial image channel that can be
transformed block by block.

Conversion back to 8-bit BGR necessarily rounds and clips values. Consequently,
the final image is not mathematically identical in the untouched chroma
channels after the color-space round trip. For transparent pixels, hidden RGB
values may shift by a small rounding amount, but the alpha values stay intact,
so those pixels remain invisible in viewers that composite transparency.

## 3. Use independent 8x8 blocks

8x8 blocks make transform processing local and give a simple, predictable
capacity calculation. Only complete blocks are used. Any rightmost or bottom
edge pixels that do not fill a whole block are left out of embedding. For a
transparent PNG, a block is eligible only if all of its alpha values are 255;
transparent and partially transparent blocks are skipped during both
embedding and extraction.

Each block carries up to four bits using these mid-frequency coordinates:

```text
(2, 3), (3, 2), (4, 1), (1, 4)
```

The DC coefficient `(0,0)` and the high-frequency bottom-right region are not
selected. Opaque images have capacity `4 * floor(height / 8) *
floor(width / 8)` bits. Transparent images have capacity four bits times their
count of fully opaque 8x8 blocks.

The 32-bit payload-length prefix consumes four more bytes of that capacity.

## 4. Provide two transform modes

Both modes use orthonormal type-II transforms from `scipy.fft`:

- **checkerboard**: DCT-II on blocks with even `(block_row + block_col)` and
  DST-II on blocks with odd `(block_row + block_col)`.
- **hybrid**: DCT-II across each block's rows followed by DST-II down its
  columns. The inverse applies IDST to columns, then IDCT to rows.

The mode is an explicit setting because extraction must repeat the same
transform selection used during embedding.

## 5. QIM balances distortion and reliability

For strength `alpha`, a coefficient is quantized to a multiple of `alpha`
whose integer index has the requested bit parity. Extraction rounds the
coefficient divided by `alpha` and reads the parity:

```text
k  = 2 * round((coefficient / alpha - bit) / 2) + bit
c' = alpha * k
bit = round(c' / alpha) mod 2
```

A larger alpha generally makes embedded bits less sensitive to small changes,
but also increases image distortion. The default is `15.0`. Verification must
use the same alpha as embedding.

This implementation is intended for lossless PNG workflows. Lossy JPEG
compression, resizing, cropping, or image edits may corrupt the QIM bits.
There is no error-correcting code or geometric synchronization.

## 6. Frame payload size before the encrypted data

A 32-bit big-endian byte length is prepended to the encrypted payload. The
extractor first reads the header, checks that the indicated payload fits the
image capacity, then extracts exactly that many bytes. This avoids a fixed
owner-string size and allows all 256 possible byte values in ciphertext.

## 7. Use lossless output and objective metrics

The CLI accepts PNG output only, so saving does not add lossy compression
artifacts. PSNR and SSIM are measured between the original and final BGR
channels; alpha is preserved but excluded from the metrics. These metrics
describe visual similarity; they do not measure authentication or resistance
to arbitrary image manipulation.

## 8. Separate responsibilities by module

- [`src/crypto_utils.py`](./src/crypto_utils.py): key derivation, encryption,
  decryption, authentication errors.
- [`src/transforms.py`](./src/transforms.py): transforms, image color-space
  conversion, inverse transforms.
- [`src/watermark.py`](./src/watermark.py): framing, capacity, QIM embedding,
  extraction, and metadata verification.
- [`src/metrics.py`](./src/metrics.py): PSNR, SSIM, and Fourier spectrum image.
- [`cli.py`](./cli.py): command-line parsing, image file I/O, output and errors.
- [`tests/test_watermark.py`](./tests/test_watermark.py): end-to-end, quality,
  password, payload-tamper, and capacity checks.

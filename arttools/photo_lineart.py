"""photo-lineart — convert photographs into line art using CV techniques.

Five styles:
  pencil   Soft artistic lines via dodge-blend (best for artistic reference)
  ink      Bold clean lines via adaptive threshold (pen/marker look)
  canny    Precise minimal edges via Canny detector (technical/architectural)
  outline  Thick clean object boundaries via bilateral filter + Sobel + dilation
  xdog     Extended Difference of Gaussians — bold felt-tip / illustration strokes

Detail levels (--detail low/medium/high) control how much fine texture is
captured vs how clean and simplified the result looks.

Extra flags:
  --darken   Push pencil lines darker via gamma curve (makes light lines pop)
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
import cv2
import numpy as np
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic", ".heif"}


# ---------------------------------------------------------------------------
# Core algorithms
# ---------------------------------------------------------------------------

def _load_gray(path: Path) -> np.ndarray:
    """Load image as grayscale numpy array with contrast normalization.

    Applies CLAHE (Contrast Limited Adaptive Histogram Equalization) so that
    low-contrast regions get their local contrast boosted before any edge
    detection runs. This is the single biggest quality improvement for
    flat or evenly-lit photos.
    """
    img = Image.open(path).convert("L")
    gray = np.array(img)
    # CLAHE: boosts local contrast without blowing out highlights
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _pencil(gray: np.ndarray, detail: str, darken: bool = False) -> np.ndarray:
    """
    Dodge-blend pencil sketch.
    Divide the grayscale image by a blurred inversion of itself.
    Produces soft, artistic lines that mimic a pencil drawing.
    --darken applies a gamma curve to push lines visibly darker.
    """
    kernel = {"low": 31, "medium": 21, "high": 11}[detail]
    inverted = 255 - gray
    blurred = cv2.GaussianBlur(inverted, (kernel, kernel), sigmaX=0)
    # Dodge blend: bright areas of blurred inversion become lines
    sketch = cv2.divide(gray, 255 - blurred, scale=256.0)
    sketch = np.clip(sketch, 0, 255).astype(np.uint8)
    # Always apply a mild gamma push so lines are visible (not just on --darken)
    gamma = 0.4 if darken else 0.65
    sketch = np.power(sketch.astype(np.float32) / 255.0, gamma) * 255.0
    return np.clip(sketch, 0, 255).astype(np.uint8)


def _ink(gray: np.ndarray, detail: str) -> np.ndarray:
    """
    Adaptive threshold ink look.
    Gives bold clean lines like a pen or marker drawing.
    """
    block = {"low": 25, "medium": 15, "high": 9}[detail]
    # Slight blur first to reduce noise
    blur_k = {"low": 5, "medium": 3, "high": 1}[detail]
    if blur_k > 1:
        gray = cv2.GaussianBlur(gray, (blur_k, blur_k), 0)
    result = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=block,
        C={"low": 6, "medium": 4, "high": 2}[detail],
    )
    return result


def _canny(gray: np.ndarray, detail: str) -> np.ndarray:
    """
    Canny edge detection.
    Produces minimal, precise lines. Good for architecture, objects, portraits.
    """
    blur_k = {"low": 7, "medium": 5, "high": 3}[detail]
    t1 = {"low": 50, "medium": 30, "high": 15}[detail]
    t2 = {"low": 150, "medium": 100, "high": 50}[detail]
    blurred = cv2.GaussianBlur(gray, (blur_k, blur_k), 0)
    edges = cv2.Canny(blurred, t1, t2)
    # Canny gives white lines on black — invert to black on white
    return 255 - edges


def _outline(gray: np.ndarray, detail: str) -> np.ndarray:
    """
    Bilateral filter + Sobel gradient + dilation.
    Produces thick, clean object boundaries — like tracing around shapes.
    Good for portraits, objects, figures. Low detail = chunkier strokes.
    """
    # Bilateral filter preserves edges while smoothing texture noise
    d = {"low": 9, "medium": 7, "high": 5}[detail]
    sigma = {"low": 75, "medium": 50, "high": 25}[detail]
    smoothed = cv2.bilateralFilter(gray, d=d, sigmaColor=sigma, sigmaSpace=sigma)

    # Sobel gradient magnitude — finds where brightness changes sharply
    sx = cv2.Sobel(smoothed, cv2.CV_64F, 1, 0, ksize=3)
    sy = cv2.Sobel(smoothed, cv2.CV_64F, 0, 1, ksize=3)
    mag = np.sqrt(sx ** 2 + sy ** 2)
    if mag.max() > 0:
        mag = mag / mag.max() * 255.0
    mag = np.clip(mag, 0, 255).astype(np.uint8)

    # Threshold: keep only strong edges — lower = more edges caught
    thresh = {"low": 15, "medium": 10, "high": 5}[detail]
    _, edges = cv2.threshold(mag, thresh, 255, cv2.THRESH_BINARY)

    # Dilate to thicken lines — lower detail = thicker strokes
    k_size = {"low": 4, "medium": 3, "high": 2}[detail]
    kernel = np.ones((k_size, k_size), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=1)

    return 255 - dilated  # black lines on white background


def _xdog(gray: np.ndarray, detail: str) -> np.ndarray:
    """
    Extended Difference of Gaussians (XDoG).
    Used in illustration software to produce bold, felt-tip-like strokes.
    Captures the gestural energy of a drawing — strong shapes, less texture.
    """
    # sigma controls stroke width; k stretches the second Gaussian far out
    sigma = {"low": 1.4, "medium": 0.9, "high": 0.5}[detail]
    k = 200.0   # ratio of second Gaussian sigma to first
    p = 20.0    # sharpening strength
    eps = 0.01  # threshold for edge/non-edge decision
    phi = 10.0  # softness of the threshold transition

    g1 = cv2.GaussianBlur(gray.astype(np.float64), (0, 0), sigma)
    g2 = cv2.GaussianBlur(gray.astype(np.float64), (0, 0), sigma * k)

    # Dog with sharpening boost
    dog = (1 + p) * g1 - p * g2

    # Soft threshold: pixels above epsilon become white, below become dark
    result = np.where(
        dog >= eps,
        1.0,
        1.0 + np.tanh(phi * (dog - eps))
    )
    result = np.clip(result * 255, 0, 255).astype(np.uint8)
    return result


def convert(
    path: Path,
    style: str = "pencil",
    detail: str = "medium",
    invert: bool = False,
    darken: bool = False,
) -> np.ndarray:
    """Convert an image file to line art. Returns grayscale numpy array."""
    gray = _load_gray(path)

    if style == "pencil":
        result = _pencil(gray, detail, darken=darken)
    elif style == "ink":
        result = _ink(gray, detail)
    elif style == "canny":
        result = _canny(gray, detail)
    elif style == "outline":
        result = _outline(gray, detail)
    elif style == "xdog":
        result = _xdog(gray, detail)
    else:
        raise ValueError(f"Unknown style: {style}")

    if invert:
        result = 255 - result

    return result


def save(arr: np.ndarray, out_path: Path) -> None:
    Image.fromarray(arr).save(out_path)


# ---------------------------------------------------------------------------
# Blend helpers
# ---------------------------------------------------------------------------

# All variant labels in the order we always generate them
VARIANT_SPECS: list[tuple[str, bool, str]] = [
    ("pencil",  False, "pencil"),
    ("pencil",  True,  "pencil-dark"),
    ("ink",     False, "ink"),
    ("canny",   False, "canny"),
    ("outline", False, "outline"),
    ("xdog",    False, "xdog"),
]


def _render_variant(gray: np.ndarray, detail: str, spec: tuple[str, bool, str]) -> np.ndarray:
    """Render a single variant from a pre-loaded gray array."""
    st, dk, _ = spec
    if st == "pencil":
        return _pencil(gray, detail, darken=dk)
    elif st == "ink":
        return _ink(gray, detail)
    elif st == "canny":
        return _canny(gray, detail)
    elif st == "outline":
        return _outline(gray, detail)
    else:
        return _xdog(gray, detail)


def _blend(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Minimum-pixel blend: wherever either image has a dark line, keep it."""
    return np.minimum(a, b)


def _score_blend(arr: np.ndarray) -> tuple[float, float]:
    """
    Score a blended image by how useful its line density is.

    Returns (density, score) where:
      density = fraction of pixels that are lines (value < 200)
      score   = 0–1, peaks at the target density (~15%), falls off on either side

    Too sparse = missing information. Too dense = noisy mess.
    """
    density = float(np.mean(arr < 200))
    target = 0.15
    # Score decays as density moves away from target
    score = 1.0 / (1.0 + 8.0 * abs(density - target))
    return density, score


def _output_path(src: Path, out: str, style: str, per_image: bool = False) -> Path:
    """Resolve output path for a given source file.

    per_image=True (used with --all-styles): puts all variants for one source
    into a subdirectory named after the source stem, e.g.:
        <out>/<stem>/<stem>-<style>.png
    """
    base = Path(out) if out else src.parent

    if per_image:
        return base / src.stem / f"{src.stem}-{style}.png"

    # Single-style path
    if out:
        p = Path(out)
        if p.is_dir():
            return p / f"{src.stem}-{style}.png"
        return p  # explicit file path
    return src.parent / f"{src.stem}-{style}.png"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument("sources", nargs=-1, required=True)
@click.option(
    "--style", "-s",
    type=click.Choice(["pencil", "ink", "canny", "outline", "xdog"]),
    default="pencil", show_default=True,
    help="Line art style.",
)
@click.option(
    "--detail", "-d",
    type=click.Choice(["low", "medium", "high"]),
    default="medium", show_default=True,
    help="Detail level. Low = clean/simplified. High = more texture/noise.",
)
@click.option(
    "--output", "-o", default="",
    help="Output path or directory. Default: same folder as source, with -{style}.png suffix.",
)
@click.option(
    "--invert", is_flag=True, default=False,
    help="Invert output: white lines on black background.",
)
@click.option(
    "--darken", is_flag=True, default=False,
    help="Darken pencil lines via gamma curve (makes faint lines pop). Pencil style only.",
)
@click.option(
    "--all-styles", is_flag=True, default=False,
    help=(
        "Generate all 6 variants (pencil, pencil-dark, ink, canny, outline, xdog) "
        "for each source. Each image gets its own subdirectory for easy comparison."
    ),
)
@click.option(
    "--best-blend", is_flag=True, default=False,
    help=(
        "Score all 15 pairwise blend combinations and save the top 3 to a "
        "best-blend/ subfolder. Prints the full ranking so you can see what worked."
    ),
)
def cli(sources, style, detail, output, invert, darken, all_styles, best_blend):
    """Convert photographs to line art.

    SOURCES can be one or more image files or directories.

    Styles:\n
      pencil   Soft dodge-blend sketch. Add --darken to push lines darker.\n
      ink      Bold adaptive threshold — pen/marker look.\n
      canny    Precise minimal edges — architectural/technical.\n
      outline  Thick clean object boundaries via bilateral filter + Sobel.\n
      xdog     Extended Difference of Gaussians — bold illustration strokes.\n

    With --all-styles, each source image gets its own subdirectory:\n
      <output>/image1/image1-pencil.png\n
      <output>/image1/image1-pencil-dark.png\n
      <output>/image1/image1-ink.png  ... etc\n

    With --best-blend, all 15 pairwise combinations are scored and the top 3\n
    are saved to <output>/image1/best-blend/. A ranked table is printed.\n

    Examples:\n
      photo-lineart photo.jpg\n
      photo-lineart photo.jpg --style pencil --darken\n
      photo-lineart photo.jpg --style outline --detail low\n
      photo-lineart photo.jpg --all-styles --output ./compare/\n
      photo-lineart photo.jpg --best-blend --output ./compare/\n
      photo-lineart *.jpg --output ./lineart/ --style pencil
    """
    # Collect all image paths
    paths: list[Path] = []
    for src in sources:
        p = Path(src)
        if p.is_dir():
            for ext in IMAGE_EXTS:
                paths.extend(p.glob(f"*{ext}"))
                paths.extend(p.glob(f"*{ext.upper()}"))
        elif p.exists():
            paths.append(p)
        else:
            click.echo(f"  Skipping (not found): {src}", err=True)

    if not paths:
        click.echo("No images found.", err=True)
        sys.exit(1)

    if best_blend:
        import itertools

        for path in paths:
            if path.suffix.lower() not in IMAGE_EXTS:
                continue
            click.echo(f"\n  {path.name} — scoring all 15 blends...")
            gray = _load_gray(path)

            # Render all 6 variants once
            rendered = {
                label: _render_variant(gray, detail, spec)
                for spec in VARIANT_SPECS
                for label in [spec[2]]
            }

            # Score every pair
            results: list[tuple[float, float, str, str, np.ndarray]] = []
            for (la, a), (lb, b) in itertools.combinations(rendered.items(), 2):
                blended = _blend(a, b)
                density, score = _score_blend(blended)
                results.append((score, density, la, lb, blended))

            results.sort(key=lambda r: r[0], reverse=True)

            # Print full ranking
            click.echo(f"\n  {'#':<3} {'Score':>6}  {'Density':>8}  Combination")
            click.echo(f"  {'-'*50}")
            for rank, (score, density, la, lb, _) in enumerate(results, 1):
                marker = "  ◀ top 3" if rank <= 3 else ""
                click.echo(f"  {rank:<3} {score:>6.3f}  {density:>7.1%}  {la} + {lb}{marker}")

            # Save top 3
            base = Path(output) if output else path.parent
            out_dir = base / path.stem / "best-blend"
            out_dir.mkdir(parents=True, exist_ok=True)

            click.echo(f"\n  Saving top 3 to {out_dir}/")
            for rank, (score, density, la, lb, arr) in enumerate(results[:3], 1):
                if invert:
                    arr = 255 - arr
                fname = f"{path.stem}-blend{rank:02d}-{la}+{lb}.png"
                save(arr, out_dir / fname)
                click.echo(f"    ✓ {fname}  (score {score:.3f}, density {density:.1%})")

        return

    if all_styles:
        # Each entry is (style_name, darken_flag, label)
        variants: list[tuple[str, bool, str]] = [
            ("pencil",  False, "pencil"),
            ("pencil",  True,  "pencil-dark"),
            ("ink",     False, "ink"),
            ("canny",   False, "canny"),
            ("outline", False, "outline"),
            ("xdog",    False, "xdog"),
        ]
        total = len(paths) * len(variants)
        done = 0

        for path in paths:
            if path.suffix.lower() not in IMAGE_EXTS:
                continue
            click.echo(f"\n  {path.name}")
            # Pre-load grayscale once per image — all variants share it
            gray = _load_gray(path)
            for st, dk, label in variants:
                try:
                    if st == "pencil":
                        arr = _pencil(gray, detail, darken=dk)
                    elif st == "ink":
                        arr = _ink(gray, detail)
                    elif st == "canny":
                        arr = _canny(gray, detail)
                    elif st == "outline":
                        arr = _outline(gray, detail)
                    else:
                        arr = _xdog(gray, detail)
                    if invert:
                        arr = 255 - arr
                    # Per-image subdir: <output>/<stem>/<stem>-<label>.png
                    base = Path(output) if output else path.parent
                    out = base / path.stem / f"{path.stem}-{label}.png"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    save(arr, out)
                    done += 1
                    click.echo(f"    ✓ {out.name}")
                except Exception as e:
                    click.echo(f"    ✗ {label}: {e}", err=True)

        click.echo(f"\n  {done}/{total} variants converted.")

    else:
        # Single-style mode — original behaviour
        total = len(paths)
        done = 0
        for path in paths:
            if path.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                arr = convert(path, style=style, detail=detail, invert=invert, darken=darken)
                out = _output_path(path, output, style)
                out.parent.mkdir(parents=True, exist_ok=True)
                save(arr, out)
                done += 1
                extra = " +darken" if darken and style == "pencil" else ""
                click.echo(f"  ✓ {out.name}  [{style}, {detail}{extra}]")
            except Exception as e:
                click.echo(f"  ✗ {path.name}: {e}", err=True)

        click.echo(f"\n  {done}/{total} converted.")

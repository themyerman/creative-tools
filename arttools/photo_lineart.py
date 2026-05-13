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


def _output_path(src: Path, out: str, style: str) -> Path:
    """Resolve output path for single-style mode."""
    if out:
        p = Path(out)
        if p.is_dir():
            return p / f"{src.stem}-{style}.png"
        return p
    return src.parent / f"{src.stem}-{style}.png"


# ---------------------------------------------------------------------------
# Post-processing: tint and line weight
# ---------------------------------------------------------------------------

def _apply_weight(arr: np.ndarray, weight: str) -> np.ndarray:
    """Adjust line thickness. Lines are dark (low values), background is white."""
    if weight == "normal":
        return arr
    k = np.ones((2, 2), np.uint8)
    if weight == "thick":
        return cv2.erode(arr, k, iterations=1)   # shrink white → fatter dark lines
    else:  # thin
        return cv2.dilate(arr, k, iterations=1)  # expand white → thinner dark lines


def _apply_tint(arr: np.ndarray, tint: str) -> np.ndarray:
    """Apply a color wash to a grayscale line art image. Returns RGB array."""
    # t=0 → line (dark), t=1 → background (light)
    t = arr.astype(np.float32) / 255.0

    if tint == "sepia":
        dark  = np.array([30,  20,  10],  dtype=np.float32)  # dark brown lines
        light = np.array([250, 240, 210], dtype=np.float32)  # warm cream background
    elif tint == "blueprint":
        dark  = np.array([210, 225, 255], dtype=np.float32)  # pale blue lines
        light = np.array([18,  38,  85],  dtype=np.float32)  # dark navy background
    elif tint == "warm":
        dark  = np.array([20,  15,  10],  dtype=np.float32)  # near-black warm lines
        light = np.array([255, 248, 235], dtype=np.float32)  # warm white background
    elif tint == "cool":
        dark  = np.array([10,  15,  25],  dtype=np.float32)  # near-black cool lines
        light = np.array([235, 242, 255], dtype=np.float32)  # cool white background
    else:
        return arr  # "none" — return grayscale unchanged

    result = dark[None, None, :] * (1 - t[:, :, None]) + light[None, None, :] * t[:, :, None]
    return np.clip(result, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument("sources", nargs=-1, required=True)
@click.option(
    "--style", "-s",
    type=click.Choice(["pencil", "ink", "canny", "outline", "xdog"]),
    default=None,
    help="Line art style. Omit to run default mode (all styles + blends, top N saved).",
)
@click.option(
    "--detail", "-d",
    type=click.Choice(["low", "medium", "high"]),
    default="medium", show_default=True,
    help="Detail level. Low = clean/simplified. High = more texture/noise.",
)
@click.option(
    "--output", "-o", default="",
    help="Output directory. Default mode saves to compare/ next to the source images.",
)
@click.option(
    "--top", "-n", default=5, show_default=True,
    help="Number of top-ranked winners to save in default mode.",
)
@click.option(
    "--tint", "-t",
    type=click.Choice(["none", "sepia", "blueprint", "warm", "cool"]),
    default="none", show_default=True,
    help="Color wash to apply: sepia (warm cream), blueprint (navy/white), warm, cool.",
)
@click.option(
    "--weight", "-w",
    type=click.Choice(["thin", "normal", "thick"]),
    default="normal", show_default=True,
    help="Line thickness adjustment.",
)
@click.option(
    "--invert", is_flag=True, default=False,
    help="Invert output: white lines on black background.",
)
@click.option(
    "--darken", is_flag=True, default=False,
    help="Darken pencil lines via gamma curve. Pencil style only.",
)
def cli(sources, style, detail, output, top, tint, weight, invert, darken):
    """Convert photographs to line art.

    DEFAULT MODE (no --style): scores all 6 style variants + 15 pairwise blends
    (21 candidates total), saves the top N into compare/<stem>/ — flat, no
    subfolders. Each filename includes its rank and score.\n

    SINGLE STYLE MODE (--style given): one output file per image.\n

    Styles:\n
      pencil   Soft dodge-blend sketch. Add --darken to push lines darker.\n
      ink      Bold adaptive threshold — pen/marker look.\n
      canny    Precise minimal edges — architectural/technical.\n
      outline  Thick clean object boundaries via bilateral filter + Sobel.\n
      xdog     Extended Difference of Gaussians — bold illustration strokes.\n

    Output options:\n
      --tint sepia      Warm cream/brown wash\n
      --tint blueprint  Dark navy background, pale blue lines\n
      --tint warm/cool  Subtle warm or cool white background\n
      --weight thick    Fatten all lines one step\n
      --weight thin     Slim all lines one step\n
      --top N           Save N winners instead of default 5\n

    Examples:\n
      photo-lineart photo.jpg\n
      photo-lineart *.jpg --top 3 --tint sepia\n
      photo-lineart photo.jpg --style ink --detail high --tint blueprint\n
      photo-lineart photo.jpg --style pencil --darken --weight thick\n
    """
    import itertools

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

    def _postprocess(arr: np.ndarray) -> np.ndarray:
        """Apply invert → weight → tint in order."""
        if invert:
            arr = 255 - arr
        arr = _apply_weight(arr, weight)
        arr = _apply_tint(arr, tint)
        return arr

    # -------------------------------------------------------------------------
    # DEFAULT MODE: rank all 21 candidates, save top N flat
    # -------------------------------------------------------------------------
    if style is None:
        for path in paths:
            if path.suffix.lower() not in IMAGE_EXTS:
                continue

            base = Path(output) if output else path.parent / "compare"
            out_dir = base / path.stem
            out_dir.mkdir(parents=True, exist_ok=True)
            click.echo(f"\n  {path.name}")

            gray = _load_gray(path)

            # Render all 6 variants
            rendered: dict[str, np.ndarray] = {
                spec[2]: _render_variant(gray, detail, spec)
                for spec in VARIANT_SPECS
            }

            # Score all 21 candidates: 6 variants + 15 blends
            candidates: list[tuple[float, float, str, np.ndarray]] = []

            for label, arr in rendered.items():
                density, score = _score_blend(arr)
                candidates.append((score, density, label, arr))

            for (la, a), (lb, b) in itertools.combinations(rendered.items(), 2):
                blended = _blend(a, b)
                density, score = _score_blend(blended)
                candidates.append((score, density, f"{la}+{lb}", blended))

            candidates.sort(key=lambda c: c[0], reverse=True)

            # Print full ranking
            click.echo(f"\n    {'#':<3} {'Score':>6}  {'Density':>8}  Candidate")
            click.echo(f"    {'-'*52}")
            for rank, (score, density, label, _) in enumerate(candidates, 1):
                marker = f"  ◀ top {top}" if rank <= top else ""
                click.echo(f"    {rank:<3} {score:>6.3f}  {density:>7.1%}  {label}{marker}")

            # Save top N
            click.echo(f"\n    Saving top {top} → {out_dir}/")
            for rank, (score, density, label, arr) in enumerate(candidates[:top], 1):
                arr = _postprocess(arr)
                fname = f"{path.stem}-top{rank:02d}-{score:.3f}-{label}.png"
                save(arr, out_dir / fname)
                click.echo(f"    ✓ {fname}")

        click.echo(f"\n  Done. Results in {Path(output) if output else paths[0].parent / 'compare'}/")

    # -------------------------------------------------------------------------
    # SINGLE STYLE MODE
    # -------------------------------------------------------------------------
    else:
        total = len(paths)
        done = 0
        for path in paths:
            if path.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                arr = convert(path, style=style, detail=detail, invert=False, darken=darken)
                arr = _postprocess(arr)
                out = _output_path(path, output, style)
                out.parent.mkdir(parents=True, exist_ok=True)
                save(arr, out)
                done += 1
                extras = []
                if darken and style == "pencil": extras.append("darken")
                if weight != "normal": extras.append(weight)
                if tint != "none": extras.append(tint)
                suffix = f"  [{', '.join(extras)}]" if extras else ""
                click.echo(f"  ✓ {out.name}  [{style}, {detail}]{suffix}")
            except Exception as e:
                click.echo(f"  ✗ {path.name}: {e}", err=True)

        click.echo(f"\n  {done}/{total} converted.")

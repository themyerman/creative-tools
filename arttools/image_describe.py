"""image-describe — generate 2-3 sentence descriptions of images using a local Ollama vision model.

Accepts a local directory of images or a web page URL (scrapes img tags).
Writes a markdown file with one entry per image: filename + description
covering subject, color/light, and mood/style.

No external API calls — runs entirely locally via Ollama (http://localhost:11434).
Requires Ollama to be installed and running with a vision model pulled, e.g.:
  ollama pull llava-llama3
"""

import base64
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError

import click


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".tif", ".bmp"}

OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = "moondream"
FALLBACK_MODELS = ["moondream", "llava-llama3", "llava", "llava:7b", "bakllava"]

DESCRIBE_PROMPT = (
    "Describe this image in 2-3 sentences. Cover: (1) the main subject or scene, "
    "(2) the color palette and lighting, and (3) the overall mood or style. "
    "Be specific and concrete. Do not speculate about meaning or symbolism."
)


def _ollama_request(endpoint: str, payload: dict) -> dict:
    """POST to the Ollama API and return parsed JSON."""
    url = f"{OLLAMA_BASE}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        click.echo(
            f"\nCannot reach Ollama at {OLLAMA_BASE}.\n"
            "Make sure Ollama is running: open /Applications/Ollama.app\n"
            f"Error: {e}",
            err=True,
        )
        sys.exit(1)


def _available_models() -> list[str]:
    """Return list of model names currently pulled in Ollama."""
    try:
        url = f"{OLLAMA_BASE}/api/tags"
        req = Request(url)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _pick_model(requested: str) -> str:
    """Return the best available vision model, or exit with instructions."""
    available = _available_models()
    # Try the requested model first (exact or prefix match)
    for name in available:
        if name == requested or name.startswith(requested.split(":")[0]):
            return name
    # Try fallbacks
    for candidate in FALLBACK_MODELS:
        for name in available:
            if name == candidate or name.startswith(candidate.split(":")[0]):
                return name
    # Nothing found
    click.echo(
        f"\nNo vision model found in Ollama. Pull one with:\n"
        f"  ollama pull llava-llama3\n\n"
        f"Available models: {available or '(none)'}",
        err=True,
    )
    sys.exit(1)


def describe_image(image_path: Path, model: str) -> str:
    """Return a 2-3 sentence description using Ollama vision."""
    image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    payload = {
        "model": model,
        "prompt": DESCRIBE_PROMPT,
        "images": [image_data],
        "stream": False,
    }
    result = _ollama_request("/api/generate", payload)
    text = result.get("response", "").strip()
    if not text:
        return "[no description returned]"
    # Strip leading answer numbering that some models (e.g. moondream) prepend
    text = re.sub(r"^\(\d+\)\s*", "", text)
    return text


def collect_local_images(directory: Path, recursive: bool = False) -> list[tuple[str, Path]]:
    """Return (name, path) pairs for all images in a directory."""
    images = []
    glob = directory.rglob("*") if recursive else directory.iterdir()
    for f in sorted(glob):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            name = f.relative_to(directory).as_posix() if recursive else f.name
            images.append((name, f))
    return images


def collect_url_images(url: str, tmp_dir: Path) -> list[tuple[str, Path]]:
    """Scrape img tags from a URL, download images, return (name, path) pairs."""
    from html.parser import HTMLParser

    class ImgScraper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.srcs = []

        def handle_starttag(self, tag, attrs):
            if tag == "img":
                attrs_dict = dict(attrs)
                src = attrs_dict.get("src") or attrs_dict.get("data-src")
                if src:
                    self.srcs.append(src)

    click.echo(f"  Fetching {url}…", err=True)
    headers = {"User-Agent": "Mozilla/5.0 (image-describe/1.0)"}
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        click.echo(f"  Failed to fetch URL: {e}", err=True)
        sys.exit(1)

    scraper = ImgScraper()
    scraper.feed(html)

    images = []
    seen = set()
    for i, src in enumerate(scraper.srcs):
        abs_src = urljoin(url, src)
        if abs_src.startswith("data:") or abs_src in seen:
            continue
        seen.add(abs_src)

        parsed = urlparse(abs_src)
        raw_name = Path(parsed.path).name or f"image-{i:03d}"
        stem = Path(raw_name).stem
        suffix = Path(raw_name).suffix.split("?")[0].lower()
        if suffix not in IMAGE_EXTS:
            suffix = ".jpg"
        filename = re.sub(r"[^\w\-.]", "_", stem) + suffix
        dest = tmp_dir / filename

        try:
            req2 = Request(abs_src, headers=headers)
            with urlopen(req2, timeout=15) as resp2:
                dest.write_bytes(resp2.read())
            images.append((filename, dest))
            click.echo(f"  Downloaded {filename}", err=True)
        except Exception as e:
            click.echo(f"  Skip {abs_src}: {e}", err=True)

    return images


@click.command()
@click.argument("source")
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output markdown file (default: image-descriptions.md next to source).",
)
@click.option(
    "--recursive", "-r",
    is_flag=True,
    default=False,
    help="Walk subdirectories (local directories only).",
)
@click.option(
    "--model", "-m",
    default=DEFAULT_MODEL,
    show_default=True,
    help="Ollama vision model to use.",
)
def cli(source: str, output: Path | None, recursive: bool, model: str):
    """Generate 2-3 sentence descriptions of images using a local Ollama vision model.

    SOURCE can be a local directory path or a web page URL.

    Requires Ollama running locally with a vision model. Install:\n
      1. Open /Applications/Ollama.app (or: brew install ollama)\n
      2. ollama pull llava-llama3\n

    Examples:\n
      image-describe ~/Desktop/inspo/\n
      image-describe ~/Desktop/art/ --output ~/Desktop/descriptions.md\n
      image-describe https://myerman.art/prints/ -o gallery.md\n
      image-describe ~/art/ --recursive --model llava
    """
    is_url = source.startswith("http://") or source.startswith("https://")
    tmp_dir_obj = None

    if is_url:
        tmp_dir_obj = tempfile.TemporaryDirectory()
        tmp_dir = Path(tmp_dir_obj.name)
        images = collect_url_images(source, tmp_dir)
        default_out = Path.cwd() / "image-descriptions.md"
    else:
        source_path = Path(source).expanduser().resolve()
        if not source_path.exists():
            click.echo(f"Directory not found: {source_path}", err=True)
            sys.exit(1)
        images = collect_local_images(source_path, recursive=recursive)
        default_out = source_path / "image-descriptions.md"

    if not images:
        click.echo("No images found.", err=True)
        sys.exit(1)

    active_model = _pick_model(model)
    click.echo(f"\n  Model: {active_model}", err=True)
    click.echo(f"  {len(images)} image(s) to describe\n", err=True)

    out_path = output or default_out

    lines = [
        "# Image Descriptions\n",
        f"Source: `{source}`  \n",
        f"Model: `{active_model}`  \n",
        f"Images: {len(images)}\n",
        "---\n",
    ]

    for i, (name, img_path) in enumerate(images, 1):
        click.echo(f"  [{i}/{len(images)}] {name}…", err=True)
        try:
            description = describe_image(img_path, active_model)
        except Exception as e:
            description = f"[error: {e}]"

        lines.append(f"## {name}\n")
        lines.append(f"{description}\n")
        lines.append("---\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    click.echo(f"\n  Written to {out_path}\n", err=True)

    if tmp_dir_obj:
        tmp_dir_obj.cleanup()

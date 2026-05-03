"""next-painting CLI — analyze a body of work and suggest what to paint next."""
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

import click
from PIL import Image

from .ai_writer import _client


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

SAMPLE_MODES = ["recent", "random", "diverse", "oldest"]


@click.command()
@click.argument("source")
@click.option("--count", "-n", default=10, show_default=True,
              help="Max number of images to analyze")
@click.option("--sample", default="recent", show_default=True,
              type=click.Choice(SAMPLE_MODES),
              help="How to select images: recent (newest files), random, diverse (even spread), oldest")
@click.option("--context", "-c", default="",
              help="Brief note about your artistic goals or interests right now")
@click.option("--style", "-s",
              type=click.Choice(["ideas", "gaps", "series", "all"]), default="all",
              show_default=True,
              help="What kind of suggestions to generate")
@click.option("--colors", is_flag=True, default=False,
              help="Extract dominant colors from each image and include in analysis")
def cli(source, count, sample, context, style, colors):
    """Analyze a body of artwork and suggest what to paint next.

    SOURCE can be a local directory of images, or a URL — fetches search.json
    if available, otherwise scrapes <img> tags (works on any portfolio site).

    Examples:\n
      next-painting ~/Desktop/new-art-for-site/png-archive\n
      next-painting ~/art/ --sample random --colors\n
      next-painting https://myerman.art --context "feeling drawn to wildlife lately"\n
      next-painting ~/art/ --style gaps --sample oldest
    """
    click.echo("\n  Analyzing your body of work...\n", err=True)

    src = source.rstrip("/")
    if src.startswith("http://") or src.startswith("https://"):
        images_desc = _fetch_from_url(src, count)
    else:
        images_desc = _scan_directory(Path(src), count, sample, colors)

    if not images_desc:
        click.echo("No images found. Check your source path or URL.", err=True)
        sys.exit(1)

    click.echo(f"  Found {len(images_desc)} works. Asking Claude for suggestions...\n", err=True)

    suggestions = _generate_suggestions(images_desc, context, style)
    click.echo(suggestions)


def _scan_directory(directory: Path, max_count: int, sample: str, extract_colors: bool) -> list[dict]:
    """Scan a directory for images, apply sampling strategy, and extract metadata."""
    if not directory.exists():
        click.echo(f"Directory not found: {directory}", err=True)
        return []

    files = [f for f in directory.iterdir() if f.suffix.lower() in IMAGE_EXTS]

    if not files:
        return []

    files = _apply_sample(files, max_count, sample)

    descriptions = []
    for f in files:
        try:
            img = Image.open(f)
            w, h = img.size
            aspect = "square" if abs(w - h) < 50 else ("landscape" if w > h else "portrait")
            entry = {
                "filename": f.stem,
                "aspect": aspect,
                "dimensions": f"{w}×{h}px",
            }
            if extract_colors:
                entry["dominant_colors"] = _extract_colors(img)
            descriptions.append(entry)
        except Exception:
            descriptions.append({"filename": f.stem, "aspect": "unknown"})

    return descriptions


def _apply_sample(files: list[Path], max_count: int, mode: str) -> list[Path]:
    """Select up to max_count files using the given sampling strategy."""
    if mode == "recent":
        files = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)
    elif mode == "oldest":
        files = sorted(files, key=lambda f: f.stat().st_mtime)
    elif mode == "random":
        files = list(files)
        random.shuffle(files)
    elif mode == "diverse":
        # Even spread across alphabetically sorted list
        files = sorted(files)
        if len(files) > max_count:
            step = len(files) // max_count
            files = files[::step]

    return files[:max_count]


def _extract_colors(img: Image.Image, n: int = 3) -> list[str]:
    """Return n dominant hex colors from an image using median-cut quantization."""
    try:
        small = img.convert("RGB").resize((150, 150), Image.LANCZOS)
        quantized = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT).convert("RGB")
        pixels = list(quantized.getdata())
        counts: dict[tuple, int] = {}
        for p in pixels:
            counts[p] = counts.get(p, 0) + 1
        top = sorted(counts, key=lambda c: -counts[c])[:n]
        return [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in top]
    except Exception:
        return []


def _fetch_from_url(base_url: str, max_count: int) -> list[dict]:
    """Fetch works from a URL. Tries /search.json first, falls back to scraping <img> tags."""
    search_url = base_url.rstrip("/") + "/search.json"
    try:
        with urllib.request.urlopen(search_url, timeout=10) as resp:
            data = json.loads(resp.read())
        works = data[:max_count]
        return [
            {
                "filename": w.get("slug", ""),
                "title": w.get("title", ""),
                "tags": ", ".join(w.get("tags", [])),
                "story": (w.get("story", "")[:120] + "…") if w.get("story") else "",
            }
            for w in works
        ]
    except Exception:
        pass

    click.echo(f"  No search.json found — scraping images from {base_url}", err=True)
    try:
        req = urllib.request.Request(base_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        click.echo(f"Could not fetch {base_url}: {e}", err=True)
        return []

    img_pattern = re.compile(r'<img[^>]+>', re.IGNORECASE)
    src_pattern  = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
    alt_pattern  = re.compile(r'\balt=["\']([^"\']*)["\']', re.IGNORECASE)

    results = []
    for tag in img_pattern.findall(html):
        src_m = src_pattern.search(tag)
        if not src_m:
            continue
        src = src_m.group(1)
        if any(skip in src.lower() for skip in ("icon", "logo", "avatar", "pixel", "spacer", "1x1")):
            continue
        ext = src.rsplit(".", 1)[-1].lower().split("?")[0]
        if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
            continue
        alt = alt_pattern.search(tag)
        filename = src.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        results.append({
            "filename": filename,
            "title": alt.group(1) if alt and alt.group(1) else filename,
            "src": src,
        })
        if len(results) >= max_count:
            break

    return results


def _generate_suggestions(works: list[dict], context: str, style: str) -> str:
    """Ask Claude to analyze the body of work and suggest next paintings."""
    works_text = json.dumps(works, indent=2)

    style_instructions = {
        "ideas":  "Focus on fresh creative ideas and new directions.",
        "gaps":   "Focus on themes, subjects, or styles that are missing or underrepresented.",
        "series": "Focus on opportunities to develop existing themes into deeper series.",
        "all":    "Cover new ideas, gaps in the catalog, and series opportunities.",
    }[style]

    context_note = f"\nThe artist notes: {context}" if context else ""

    prompt = (
        "You are a creative advisor to Tom Myer, a Hodinǫ̱hsǫ́:nih and Ngäbe-Buglé "
        "Indigenous digital artist based in Colorado. His work spans wildlife, futurism, "
        "Indigenous culture and politics, and abstract art."
        f"{context_note}\n\n"
        f"Here is a sample of his recent body of work:\n{works_text}\n\n"
        f"{style_instructions}\n\n"
        "Respond with:\n"
        "1. **What I see in this body of work** (2-3 sentences on themes, strengths, patterns — "
        "note any patterns in aspect ratio or color palette if that data is present)\n"
        "2. **5 specific painting suggestions** — each with a working title, a one-sentence description, "
        "and why it fits or extends this body of work\n"
        "3. **One bold idea** — something unexpected that would push the work in a new direction\n\n"
        "Be specific and grounded in what you actually see in the work. Avoid generic advice."
    )

    msg = _client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()

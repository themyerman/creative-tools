"""next-painting CLI — analyze a body of work and suggest what to paint next."""
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

import click
from PIL import Image

from .ai_writer import _client


# Supported image extensions
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@click.command()
@click.argument("source")
@click.option("--count", "-n", default=10, show_default=True,
              help="Max number of images to analyze (sampled if more exist)")
@click.option("--context", "-c", default="",
              help="Brief note about your artistic goals or interests right now")
@click.option("--style", "-s",
              type=click.Choice(["ideas", "gaps", "series", "all"]), default="all",
              show_default=True,
              help="What kind of suggestions to generate")
def cli(source, count, context, style):
    """Analyze a body of artwork and suggest what to paint next.

    SOURCE can be a local directory of images, or a base URL
    (e.g. https://myerman.art/prints/) — the tool will fetch image list from search.json.

    Examples:\n
      next-painting ~/Desktop/new-art-for-site/png-archive\n
      next-painting https://myerman.art --context "feeling drawn to wildlife lately"\n
      next-painting ~/art/ --style gaps
    """
    click.echo("\n  Analyzing your body of work...\n", err=True)

    images_desc = _load_image_descriptions(source, count)

    if not images_desc:
        click.echo("No images found. Check your source path or URL.", err=True)
        sys.exit(1)

    click.echo(f"  Found {len(images_desc)} works. Asking Claude for suggestions...\n", err=True)

    suggestions = _generate_suggestions(images_desc, context, style)
    click.echo(suggestions)


def _load_image_descriptions(source: str, max_count: int) -> list[dict]:
    """Load image metadata from a directory or from myerman.art's search.json."""
    src = source.rstrip("/")

    if src.startswith("http://") or src.startswith("https://"):
        return _fetch_from_site(src, max_count)
    else:
        return _scan_directory(Path(src), max_count)


def _scan_directory(directory: Path, max_count: int) -> list[dict]:
    """Scan a directory for images and extract basic metadata."""
    if not directory.exists():
        click.echo(f"Directory not found: {directory}", err=True)
        return []

    files = [f for f in sorted(directory.iterdir())
             if f.suffix.lower() in IMAGE_EXTS]

    # Sample evenly if more than max_count
    if len(files) > max_count:
        step = len(files) // max_count
        files = files[::step][:max_count]

    descriptions = []
    for f in files:
        try:
            img = Image.open(f)
            w, h = img.size
            aspect = "square" if abs(w - h) < 50 else ("landscape" if w > h else "portrait")
            descriptions.append({
                "filename": f.stem,
                "aspect": aspect,
                "size": f"{w}x{h}",
            })
        except Exception:
            descriptions.append({"filename": f.stem, "aspect": "unknown", "size": "unknown"})

    return descriptions


def _fetch_from_site(base_url: str, max_count: int) -> list[dict]:
    """Fetch the works list from myerman.art's search.json."""
    # Try /search.json
    search_url = base_url.rstrip("/") + "/search.json"
    try:
        with urllib.request.urlopen(search_url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        click.echo(f"Could not fetch {search_url}: {e}", err=True)
        return []

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
        "1. **What I see in this body of work** (2-3 sentences on themes, strengths, patterns)\n"
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

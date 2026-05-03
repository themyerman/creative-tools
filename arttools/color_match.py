"""color-match CLI — compare color palettes between two images."""
import json
import math
import sys

import click

from .palette import extract_colors


@click.command()
@click.argument("image_a")
@click.argument("image_b")
@click.option("--colors", "-n", default=6, show_default=True,
              help="Number of palette colors to compare")
@click.option("--format", "-f", "fmt",
              type=click.Choice(["terminal", "json"]), default="terminal", show_default=True)
def cli(image_a, image_b, colors, fmt):
    """Compare the color palettes of two images.

    Shows dominant colors side-by-side, a similarity score (0–100),
    and which colors are shared vs. unique to each image.

    IMAGE_A and IMAGE_B can be local file paths or https:// URLs.

    Examples:\n
      color-match painting-1.png painting-2.png\n
      color-match series-1.jpg series-2.jpg --colors 8\n
      color-match https://myerman.art/prints/wolf/display.jpg ./new-wolf.png
    """
    try:
        palette_a = extract_colors(image_a, n=colors)
        palette_b = extract_colors(image_b, n=colors)
    except Exception as e:
        click.echo(f"Could not load images: {e}", err=True)
        sys.exit(1)

    score = _similarity_score(palette_a, palette_b)
    shared, only_a, only_b = _classify_colors(palette_a, palette_b)

    if fmt == "json":
        click.echo(json.dumps({
            "similarity": score,
            "palette_a": palette_a,
            "palette_b": palette_b,
            "shared": shared,
            "only_a": only_a,
            "only_b": only_b,
        }, indent=2))
    else:
        _render_terminal(image_a, image_b, palette_a, palette_b, score, shared, only_a, only_b)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _color_distance(a: str, b: str) -> float:
    """Perceptual color distance using CIE76-approximation in RGB space."""
    r1, g1, b1 = _hex_to_rgb(a)
    r2, g2, b2 = _hex_to_rgb(b)
    return math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)


def _similarity_score(palette_a: list[dict], palette_b: list[dict]) -> int:
    """0–100 score: how similar the two palettes are overall."""
    max_dist = math.sqrt(3 * 255 ** 2)  # max possible RGB distance
    hexes_a = [c["hex"] for c in palette_a]
    hexes_b = [c["hex"] for c in palette_b]

    total = 0.0
    for ha in hexes_a:
        # Best match in palette_b for this color
        best = min(_color_distance(ha, hb) for hb in hexes_b)
        total += best / max_dist

    avg_dist = total / len(hexes_a) if hexes_a else 1.0
    return round((1 - avg_dist) * 100)


def _classify_colors(
    palette_a: list[dict], palette_b: list[dict], threshold: float = 60.0
) -> tuple[list, list, list]:
    """Split colors into shared (close match) and unique to each palette."""
    shared, only_a, only_b = [], [], []
    matched_b = set()

    for ca in palette_a:
        best_dist = float("inf")
        best_idx = -1
        for i, cb in enumerate(palette_b):
            d = _color_distance(ca["hex"], cb["hex"])
            if d < best_dist:
                best_dist = d
                best_idx = i
        if best_dist <= threshold and best_idx not in matched_b:
            shared.append({"a": ca["hex"], "b": palette_b[best_idx]["hex"], "distance": round(best_dist)})
            matched_b.add(best_idx)
        else:
            only_a.append(ca["hex"])

    for i, cb in enumerate(palette_b):
        if i not in matched_b:
            only_b.append(cb["hex"])

    return shared, only_a, only_b


def _swatch(hex_color: str) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"\033[48;2;{r};{g};{b}m  \033[0m"


def _render_terminal(
    name_a, name_b, palette_a, palette_b, score, shared, only_a, only_b
):
    label = "identical" if score >= 95 else \
            "very similar" if score >= 80 else \
            "similar" if score >= 60 else \
            "some overlap" if score >= 40 else \
            "quite different"

    a_short = str(name_a).rsplit("/", 1)[-1]
    b_short = str(name_b).rsplit("/", 1)[-1]

    click.echo(f"\n  Similarity: {score}/100  ({label})\n")

    # Side-by-side palettes
    click.echo(f"  {'A: ' + a_short:<40}  B: {b_short}")
    max_len = max(len(palette_a), len(palette_b))
    for i in range(max_len):
        ca = palette_a[i] if i < len(palette_a) else None
        cb = palette_b[i] if i < len(palette_b) else None
        a_str = f"  {_swatch(ca['hex'])} {ca['hex']}  ({ca['frequency']}%)" if ca else ""
        b_str = f"  {_swatch(cb['hex'])} {cb['hex']}  ({cb['frequency']}%)" if cb else ""
        click.echo(f"  {a_str:<40}{b_str}")

    if shared:
        click.echo(f"\n  Shared tones ({len(shared)}):")
        for s in shared:
            click.echo(f"    {_swatch(s['a'])} {s['a']}  ↔  {_swatch(s['b'])} {s['b']}  "
                       f"(Δ {s['distance']})")

    if only_a:
        click.echo(f"\n  Only in A:")
        for h in only_a:
            click.echo(f"    {_swatch(h)} {h}")

    if only_b:
        click.echo(f"\n  Only in B:")
        for h in only_b:
            click.echo(f"    {_swatch(h)} {h}")

    click.echo()

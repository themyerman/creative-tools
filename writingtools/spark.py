"""daily-spark CLI — generate a set of genre writing prompts via GitHub Models."""
import json
import os
import sys
from importlib import resources
from pathlib import Path

import click
import yaml

from .render import render_email
from .mailer import send


def _load_config(config_path: str | None) -> dict:
    """Load config from path, SPARK_CONFIG env var, or bundled default."""
    path = config_path or os.environ.get("SPARK_CONFIG")
    if path:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    bundled = Path(__file__).parent / "config.yaml"
    return yaml.safe_load(bundled.read_text(encoding="utf-8"))


def _build_genres(config: dict) -> dict:
    """Convert config genres section into the runtime GENRES dict."""
    genres = {}
    for key, g in config.get("genres", {}).items():
        influences = g.get("influences", [])
        prefs = g.get("preferences", "").strip()
        if influences:
            inf_str = ", ".join(influences)
            prefs = f"{prefs} Tonal influences: {inf_str}."
        genres[key] = {
            "label": g["label"],
            "icon": g["icon"],
            "color": g["color"],
            "preferences": prefs,
        }
    return genres


@click.command()
@click.option("--config", "config_path", default=None, metavar="FILE",
              help="Path to a YAML config file (default: bundled config.yaml)")
@click.option("--email", is_flag=True, default=False,
              help="Generate prompts and send via email")
@click.option("--genre", type=str, default=None,
              help="Generate only one genre (must match a key in config)")
@click.option("--model", default="gpt-4o-mini", show_default=True,
              help="GitHub Models model ID to use")
@click.option("--print-html", is_flag=True, default=False,
              help="Print the rendered HTML to stdout instead of sending")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write HTML to a file (e.g. docs/index.html)")
def cli(config_path, email, genre, model, print_html, output):
    """Generate daily writing sparks — one prompt per genre — via GitHub Models.

    Requires GITHUB_TOKEN in the environment. To email, also requires
    EMAIL_SMTP_HOST, EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO.

    Customize genres and author influences by pointing --config at your own YAML.
    The bundled config.yaml is the documented starting point.

    Examples:\n
      daily-spark\n
      daily-spark --email\n
      daily-spark --genre sf\n
      daily-spark --config ~/my-spark.yaml\n
      daily-spark --model openai/gpt-4o
    """
    config = _load_config(config_path)
    all_genres = _build_genres(config)
    writer_profile = config.get("writer_profile", {})

    if genre:
        if genre not in all_genres:
            click.echo(f"Unknown genre '{genre}'. Available: {', '.join(all_genres)}", err=True)
            sys.exit(1)
        genres = {genre: all_genres[genre]}
    else:
        genres = all_genres

    click.echo(f"\n  Generating {len(genres)} prompt(s) via GitHub Models ({model})...\n", err=True)

    prompts = _generate_prompts(genres, model, writer_profile)

    if not prompts:
        click.echo("No prompts generated. Check your GITHUB_TOKEN.", err=True)
        sys.exit(1)

    html = render_email(prompts, genres)

    if print_html:
        click.echo(html)
        return

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(html, encoding="utf-8")
        click.echo(f"  Written to {output}", err=True)
        return

    # Always print to terminal
    for key, p in prompts.items():
        g = genres[key]
        click.echo(f"  {g['icon']}  {g['label']}")
        click.echo(f"  {p}\n")

    if email:
        click.echo("  Sending email...", err=True)
        send(html)
        click.echo("  Done.", err=True)


def _generate_prompts(genres: dict, model: str, writer_profile: dict | None = None) -> dict[str, str]:
    """Call GitHub Models and return {genre_key: prompt_text}."""
    client = _github_client()

    genre_list = "\n".join(
        f'- "{key}": {g["label"]} — {g["preferences"]}'
        for key, g in genres.items()
    )

    profile_block = ""
    if writer_profile:
        background = writer_profile.get("background", "").strip()
        influences = writer_profile.get("influences", [])
        parts = []
        if background:
            parts.append(f"Writer background: {background}")
        if influences:
            parts.append("Cross-genre literary touchstones: " + "; ".join(influences))
        if parts:
            profile_block = "\n\n" + " ".join(parts)

    prompt = (
        "You are a creative writing spark generator. Your job is to produce specific, "
        "evocative writing prompts — not themes or topics, but *situations*. "
        "Each prompt should have a character in a specific moment of tension or discovery, "
        "a vivid setting detail, and enough open space for the writer to go anywhere. "
        "2-3 sentences max. No generic advice. No 'write a story about'. Just the spark."
        f"{profile_block}\n\n"
        f"Generate one prompt for each of these genres, matching the stated preferences:\n{genre_list}\n\n"
        "Respond with JSON only — no explanation, no markdown:\n"
        "{\n"
        + ",\n".join(f'  "{k}": "prompt text here"' for k in genres)
        + "\n}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception as e:
        click.echo(f"Generation error: {e}", err=True)
        return {}


def _github_client():
    """Return an OpenAI client pointed at GitHub Models."""
    from openai import OpenAI
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN not set. Export it or add it to your environment."
        )
    return OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )

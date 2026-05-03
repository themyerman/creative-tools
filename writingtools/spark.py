"""daily-spark CLI — generate a set of genre writing prompts via GitHub Models."""
import json
import os
import sys

import click

from .render import render_email
from .mailer import send


GENRES = {
    "sf": {
        "label": "Science Fiction",
        "icon": "🚀",
        "color": "#1a3a5c",
        "preferences": (
            "space opera, alternate histories, dystopias, solarpunk, and Indigenous futurism. "
            "The writer is a Hodinǫ̱hsǫ́:nih and Ngäbe-Buglé Indigenous author — "
            "prompts that touch Indigenous futures, sovereignty, or relationships with land and cosmos are especially welcome."
        ),
    },
    "fantasy": {
        "label": "Fantasy",
        "icon": "⚔️",
        "color": "#2d1b4e",
        "preferences": (
            "grimdark fantasy. Moral ambiguity, hard choices, consequences that linger. "
            "No chosen-one tropes. No clean endings required."
        ),
    },
    "western": {
        "label": "Western",
        "icon": "🌵",
        "color": "#4a2c0a",
        "preferences": (
            "neo-westerns and classic westerns, with special attention to Indigenous perspectives "
            "and characters. The frontier from the other side. Land, survival, justice on the margins."
        ),
    },
    "mystery": {
        "label": "Mystery",
        "icon": "🕵️",
        "color": "#1a2a1a",
        "preferences": (
            "noir mysteries but also cozy detective fiction in the vein of Poirot or Midsommar Murders. "
            "A good puzzle, a strong sense of place, and a detective with an interesting perspective."
        ),
    },
}


@click.command()
@click.option("--email", is_flag=True, default=False,
              help="Generate prompts and send via email")
@click.option("--genre", type=click.Choice(list(GENRES)), default=None,
              help="Generate only one genre (default: all four)")
@click.option("--model", default="gpt-4o-mini", show_default=True,
              help="GitHub Models model ID to use")
@click.option("--print-html", is_flag=True, default=False,
              help="Print the rendered HTML to stdout instead of sending")
def cli(email, genre, model, print_html):
    """Generate daily writing sparks — one prompt per genre — via GitHub Models.

    Requires GITHUB_TOKEN in the environment. To email, also requires
    EMAIL_SMTP_HOST, EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO.

    Examples:\n
      daily-spark\n
      daily-spark --email\n
      daily-spark --genre sf\n
      daily-spark --model openai/gpt-4o
    """
    genres = {genre: GENRES[genre]} if genre else GENRES

    click.echo(f"\n  Generating {len(genres)} prompt(s) via GitHub Models ({model})...\n", err=True)

    prompts = _generate_prompts(genres, model)

    if not prompts:
        click.echo("No prompts generated. Check your GITHUB_TOKEN.", err=True)
        sys.exit(1)

    html = render_email(prompts, genres)

    if print_html:
        click.echo(html)
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


def _generate_prompts(genres: dict, model: str) -> dict[str, str]:
    """Call GitHub Models and return {genre_key: prompt_text}."""
    client = _github_client()

    genre_list = "\n".join(
        f'- "{key}": {g["label"]} — {g["preferences"]}'
        for key, g in genres.items()
    )

    prompt = (
        "You are a creative writing spark generator. Your job is to produce specific, "
        "evocative writing prompts — not themes or topics, but *situations*. "
        "Each prompt should have a character in a specific moment of tension or discovery, "
        "a vivid setting detail, and enough open space for the writer to go anywhere. "
        "2-3 sentences max. No generic advice. No 'write a story about'. Just the spark.\n\n"
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

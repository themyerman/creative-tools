"""daily-spark CLI — generate story starter cards via GitHub Models."""
import json
import os
import random
import sys
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
        screen = g.get("screen_influences", [])
        prefs = g.get("preferences", "").strip()
        if influences:
            prefs = f"{prefs} Literary influences: {', '.join(influences)}."
        if screen:
            prefs = f"{prefs} Screen influences: {', '.join(screen)}."
        genres[key] = {
            "label": g["label"],
            "icon": g["icon"],
            "color": g["color"],
            "preferences": prefs,
        }
    return genres


def _collect_all_influences(config: dict) -> list[str]:
    """Collect every named influence across writer profile and all genres."""
    influences = []
    influences.extend(config.get("writer_profile", {}).get("influences", []))
    for g in config.get("genres", {}).values():
        influences.extend(g.get("influences", []))
        influences.extend(g.get("screen_influences", []))
    return influences


def _assign_voices(keys: list[str], voices: dict) -> dict[str, str]:
    """Assign a unique voice to each key, no repeats."""
    voice_names = list(voices.keys())
    if len(keys) <= len(voice_names):
        chosen = random.sample(voice_names, len(keys))
    else:
        chosen = []
        while len(chosen) < len(keys):
            chunk = voice_names[:]
            random.shuffle(chunk)
            chosen.extend(chunk)
        chosen = chosen[:len(keys)]
    return {key: chosen[i] for i, key in enumerate(keys)}


def _sample_no_repeat(pool: list, n: int) -> list:
    """Sample n items without replacement, tiling if n > len(pool)."""
    if n <= len(pool):
        return random.sample(pool, n)
    result = []
    while len(result) < n:
        chunk = pool[:]
        random.shuffle(chunk)
        result.extend(chunk)
    return result[:n]


@click.command()
@click.option("--config", "config_path", default=None, metavar="FILE",
              help="Path to a YAML config file (default: bundled config.yaml)")
@click.option("--email", is_flag=True, default=False,
              help="Generate story starters and send via email")
@click.option("--count", default=3, show_default=True,
              help="Number of story starter cards to generate")
@click.option("--genre", type=str, default=None,
              help="Generate one specific genre only")
@click.option("--model", default="gpt-4o-mini", show_default=True,
              help="GitHub Models model ID to use")
@click.option("--print-html", is_flag=True, default=False,
              help="Print rendered HTML to stdout")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write HTML to a file (e.g. docs/index.html)")
def cli(config_path, email, count, genre, model, print_html, output):
    """Generate story starter cards — protagonist, antagonist, conflict — via GitHub Models.

    Each card picks a random genre, voice, and influence lens. No repeats across cards.

    Requires GITHUB_TOKEN in the environment.

    Examples:\n
      daily-spark\n
      daily-spark --count 5\n
      daily-spark --genre sf\n
      daily-spark --config ~/my-spark.yaml
    """
    config = _load_config(config_path)
    all_genres = _build_genres(config)
    writer_profile = config.get("writer_profile", {})
    voices = config.get("voices", {})
    all_influences = _collect_all_influences(config)

    if genre:
        if genre not in all_genres:
            click.echo(f"Unknown genre '{genre}'. Available: {', '.join(all_genres)}", err=True)
            sys.exit(1)
        selected_keys = [genre]
    else:
        n = min(count, len(all_genres))
        selected_keys = random.sample(list(all_genres.keys()), n)

    voice_map = _assign_voices(selected_keys, voices)
    influence_map = {k: inf for k, inf in zip(
        selected_keys, _sample_no_repeat(all_influences, len(selected_keys))
    )}

    click.echo(f"  Generating {len(selected_keys)} story starter(s) via GitHub Models ({model})...\n", err=True)

    cards = _generate_starters(
        selected_keys, all_genres, model, writer_profile, voice_map, influence_map
    )

    if not cards:
        click.echo("No starters generated. Check your GITHUB_TOKEN.", err=True)
        sys.exit(1)

    html = render_email(cards, all_genres, voice_map, influence_map)

    if print_html:
        click.echo(html)
        return

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(html, encoding="utf-8")
        click.echo(f"  Written to {output}", err=True)
        return

    for key, card in cards.items():
        g = all_genres[key]
        click.echo(f"  {g['icon']}  {g['label']}  [{voice_map[key]}]")
        click.echo(f"  via {influence_map[key]}")
        click.echo(f"  {card['prompt']}")
        click.echo(f"  \"{card['opening']}\"")
        click.echo("")

    if email:
        click.echo("  Sending email...", err=True)
        send(html)
        click.echo("  Done.", err=True)


def _generate_starters(
    keys: list[str],
    genres: dict,
    model: str,
    writer_profile: dict | None = None,
    voice_map: dict | None = None,
    influence_map: dict | None = None,
) -> dict[str, dict]:
    """Call GitHub Models and return {genre_key: {protagonist, antagonist, conflict}}."""
    client = _github_client()

    entries = []
    for key in keys:
        g = genres[key]
        voice = (voice_map or {}).get(key, "")
        influence = (influence_map or {}).get(key, "")
        entries.append(
            f'- "{key}": {g["label"]}\n'
            f'  Genre preferences: {g["preferences"]}\n'
            f'  Voice style: {voice}\n'
            f'  Influence lens: {influence}'
        )

    profile_block = _profile_block(writer_profile)

    opening_styles = ["dialogue", "action", "description", "interior thought", "in medias res"]
    random.shuffle(opening_styles)
    style_map = {k: opening_styles[i % len(opening_styles)] for i, k in enumerate(keys)}

    response_shape = (
        "{\n"
        + ",\n".join(
            f'  "{k}": {{"prompt": "one or two sentences", "opening": "one sentence"}}'
            for k in keys
        )
        + "\n}"
    )

    style_instructions = "\n".join(
        f'- "{k}": opening line style — {style_map[k]}' for k in keys
    )

    prompt = (
        "You are a story development tool. For each genre entry, generate two things:\n\n"
        "- prompt: a vivid story situation — specific people, a charged moment, something "
        "that has just happened or is about to. Atmospheric, load-bearing detail. "
        "Two or three sentences. Let the second or third sentence deepen or complicate the first. "
        "No generic setups.\n"
        "- opening: the actual first line of the story — the words on page one. "
        "Use the style specified per entry. One sentence, punchy, specific. "
        "It should make the reader lean forward.\n\n"
        "Opening line styles per entry:\n"
        f"{style_instructions}\n\n"
        "Apply the voice style to shape the language and tone of both elements.\n"
        "The influence lens is your primary creative constraint — not a vague nod, a direct borrowing. "
        "The parenthetical tells you exactly what to take: if it says 'bureaucratic dread', put bureaucratic dread in the bones of the situation. "
        "If it says 'the long game, patience as weapon', build a situation where patience is the only weapon that matters. "
        "The world, the moral texture, the character logic — all of it should feel like it came from that specific lens.\n"
        "Be specific — names, places, sensory detail. No generic archetypes."
        f"{profile_block}\n\n"
        "Entries:\n" + "\n".join(entries) + "\n\n"
        "Respond with JSON only — no explanation, no markdown:\n"
        f"{response_shape}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=2400,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception as e:
        click.echo(f"Generation error: {e}", err=True)
        return {}


def _profile_block(writer_profile: dict | None) -> str:
    if not writer_profile:
        return ""
    parts = []
    background = writer_profile.get("background", "").strip()
    influences = writer_profile.get("influences", [])
    if background:
        parts.append(f"Writer background: {background}")
    if influences:
        parts.append("Cross-genre touchstones: " + "; ".join(influences))
    return ("\n\n" + " ".join(parts)) if parts else ""


def _github_client():
    """Return an OpenAI client pointed at GitHub Models."""
    from openai import OpenAI
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set.")
    return OpenAI(base_url="https://models.inference.ai.azure.com", api_key=token)

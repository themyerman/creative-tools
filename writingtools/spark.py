"""daily-spark CLI — generate a set of genre writing prompts via GitHub Models."""
import json
import os
import random
import sys
from pathlib import Path

import click
import yaml

from .render import render_email
from .mailer import send

WILDCARD_KEY = "__wildcard__"


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


def _build_wildcard(config: dict, genres: dict, voices: dict) -> dict:
    """Pick two random genres, one voice, one influence and return wildcard metadata."""
    genre_keys = random.sample(list(genres.keys()), 2)
    g1, g2 = genres[genre_keys[0]], genres[genre_keys[1]]
    voice_name = random.choice(list(voices.keys()))
    influence = random.choice(_collect_all_influences(config))
    return {
        "genre_keys": genre_keys,
        "genre_labels": [g1["label"], g2["label"]],
        "genre_icons": [g1["icon"], g2["icon"]],
        "genre_prefs": [g1["preferences"], g2["preferences"]],
        "voice_name": voice_name,
        "voice_instruction": voices[voice_name],
        "influence": influence,
    }


def _assign_voices(genres: dict, voice: str, voices: dict) -> dict[str, str]:
    """Return {genre_key: voice_instruction}. 'random' assigns each voice at most once per run."""
    if voice == "random":
        voice_names = list(voices.keys())
        if len(genres) <= len(voice_names):
            chosen = random.sample(voice_names, len(genres))
        else:
            chosen = []
            while len(chosen) < len(genres):
                chunk = voice_names[:]
                random.shuffle(chunk)
                chosen.extend(chunk)
            chosen = chosen[:len(genres)]
        return {key: voices[name] for key, name in zip(genres, chosen)}
    instruction = voices.get(voice, voices.get("vanilla", ""))
    return {key: instruction for key in genres}


@click.command()
@click.option("--config", "config_path", default=None, metavar="FILE",
              help="Path to a YAML config file (default: bundled config.yaml)")
@click.option("--email", is_flag=True, default=False,
              help="Generate prompts and send via email")
@click.option("--genre", type=str, default=None,
              help="Generate only one genre (must match a key in config)")
@click.option("--model", default="gpt-4o-mini", show_default=True,
              help="GitHub Models model ID to use")
@click.option("--voice", default="random", show_default=True,
              help="Voice style: vanilla, trailer, bestseller, xfiles, trashy, campfire, kenburns, "
                   "pulp, academic, satiric, telegram, gothic, broadsheet, bard, goldman, tarantino, "
                   "beat, dispatch, southern_gothic, magic_realism, fairy_tale, manifesto, "
                   "or 'random' (default)")
@click.option("--wildcard/--no-wildcard", default=True,
              help="Generate a genre-mashup wild card prompt at the top (default: on)")
@click.option("--count", default=7, show_default=True,
              help="Number of genres to sample per run (ignored if --genre is set)")
@click.option("--print-html", is_flag=True, default=False,
              help="Print the rendered HTML to stdout instead of sending")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write HTML to a file (e.g. docs/index.html)")
def cli(config_path, email, genre, model, voice, wildcard, count, print_html, output):
    """Generate daily writing sparks — one prompt per genre — via GitHub Models.

    Requires GITHUB_TOKEN in the environment. To email, also requires
    EMAIL_SMTP_HOST, EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO.

    Customize genres and author influences by pointing --config at your own YAML.
    The bundled config.yaml is the documented starting point.

    Examples:\n
      daily-spark\n
      daily-spark --voice trailer\n
      daily-spark --no-wildcard\n
      daily-spark --genre sf --voice campfire\n
      daily-spark --config ~/my-spark.yaml
    """
    config = _load_config(config_path)
    all_genres = _build_genres(config)
    writer_profile = config.get("writer_profile", {})
    voices = config.get("voices", {})

    if genre:
        if genre not in all_genres:
            click.echo(f"Unknown genre '{genre}'. Available: {', '.join(all_genres)}", err=True)
            sys.exit(1)
        genres = {genre: all_genres[genre]}
        wildcard = False
    else:
        n = min(count, len(all_genres))
        sampled_keys = random.sample(list(all_genres.keys()), n)
        genres = {k: all_genres[k] for k in sampled_keys}

    voice_map = _assign_voices(genres, voice, voices)
    voice_name_map = {v: n for n, v in voices.items()}
    assigned_voice_names = {k: voice_name_map.get(voice_map[k], voice) for k in genres}

    wc_meta = _build_wildcard(config, all_genres, voices) if wildcard else None

    click.echo(f"  Generating {len(genres)} prompt(s) via GitHub Models ({model})...\n", err=True)

    result = _generate_prompts(genres, model, writer_profile, voice_map, wildcard=wc_meta)

    prompts = {k: v for k, v in result.items() if k != WILDCARD_KEY}
    wc_prompt = result.get(WILDCARD_KEY)

    if not prompts:
        click.echo("No prompts generated. Check your GITHUB_TOKEN.", err=True)
        sys.exit(1)

    html = render_email(prompts, genres, assigned_voice_names, wc_meta, wc_prompt)

    if print_html:
        click.echo(html)
        return

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(html, encoding="utf-8")
        click.echo(f"  Written to {output}", err=True)
        return

    if wc_meta and wc_prompt:
        labels = " × ".join(wc_meta["genre_labels"])
        icons = " ".join(wc_meta["genre_icons"])
        click.echo(f"  ⚡  WILD CARD  {icons}  {labels}  [{wc_meta['voice_name']}]")
        click.echo(f"  via: {wc_meta['influence']}")
        click.echo(f"  {wc_prompt}\n")

    for key, p in prompts.items():
        g = genres[key]
        vname = assigned_voice_names.get(key, voice)
        click.echo(f"  {g['icon']}  {g['label']}  [{vname}]")
        click.echo(f"  {p}\n")

    if email:
        click.echo("  Sending email...", err=True)
        send(html)
        click.echo("  Done.", err=True)


def _generate_prompts(
    genres: dict,
    model: str,
    writer_profile: dict | None = None,
    voice_map: dict[str, str] | None = None,
    wildcard: dict | None = None,
) -> dict[str, str]:
    """Call GitHub Models and return {genre_key: prompt_text} strings."""
    client = _github_client()

    genre_lines = []
    for key, g in genres.items():
        voice_instruction = (voice_map or {}).get(key, "")
        voice_note = f" Voice style: {voice_instruction}" if voice_instruction else ""
        genre_lines.append(f'- "{key}": {g["label"]} — {g["preferences"]}{voice_note}')

    if wildcard:
        g1_label, g2_label = wildcard["genre_labels"]
        g1_prefs, g2_prefs = wildcard["genre_prefs"]
        genre_lines.append(
            f'- "{WILDCARD_KEY}": WILD CARD — Mash together {g1_label} and {g2_label}. '
            f'{g1_label} preferences: {g1_prefs} {g2_label} preferences: {g2_prefs} '
            f'Channel the specific influence of: {wildcard["influence"]}. '
            f'Voice style: {wildcard["voice_instruction"]} '
            f'Make this feel genuinely surprising — the two genres should collide, not just coexist.'
        )

    genre_list = "\n".join(genre_lines)

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

    all_keys = list(genres.keys()) + ([WILDCARD_KEY] if wildcard else [])
    response_shape = (
        "{\n"
        + ",\n".join(f'  "{k}": "prompt text here"' for k in all_keys)
        + "\n}"
    )

    prompt = (
        "You are a creative writing spark generator. Your job is to produce specific, "
        "evocative writing prompts — not themes or topics, but *situations*. "
        "Each prompt should place a character in a specific moment of tension or discovery "
        "with a vivid setting detail, leaving open space for the writer to go anywhere. "
        "2-3 sentences max. No generic advice. No 'write a story about'. Just the spark. "
        "Apply the voice style instruction for each entry exactly as described."
        f"{profile_block}\n\n"
        f"Generate one prompt for each of these entries:\n{genre_list}\n\n"
        "Respond with JSON only — no explanation, no markdown:\n"
        f"{response_shape}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=2500,
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

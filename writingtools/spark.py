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


def _assign_voices(genres: dict, voice: str, voices: dict) -> dict[str, str]:
    """Return {genre_key: voice_instruction}. 'random' assigns each voice at most once per run."""
    if voice == "random":
        voice_names = list(voices.keys())
        if len(genres) <= len(voice_names):
            chosen = random.sample(voice_names, len(genres))
        else:
            # More genres than voices — shuffle and tile, still no back-to-back repeats
            chosen = []
            while len(chosen) < len(genres):
                chunk = voice_names[:]
                random.shuffle(chunk)
                chosen.extend(chunk)
            chosen = chosen[:len(genres)]
        return {key: voices[name] for key, name in zip(genres, chosen)}
    instruction = voices.get(voice, voices.get("neutral", ""))
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
              help="Voice style: neutral, trailer, bestseller, xfiles, trashy, campfire, "
                   "kenburns, pulp, academic, satiric, or 'random' to assign a different voice per genre")
@click.option("--beats/--no-beats", default=True,
              help="Generate 6-7 plot beats per prompt (shown as expandable section in HTML)")
@click.option("--print-html", is_flag=True, default=False,
              help="Print the rendered HTML to stdout instead of sending")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write HTML to a file (e.g. docs/index.html)")
def cli(config_path, email, genre, model, voice, beats, print_html, output):
    """Generate daily writing sparks — one prompt per genre — via GitHub Models.

    Requires GITHUB_TOKEN in the environment. To email, also requires
    EMAIL_SMTP_HOST, EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO.

    Customize genres and author influences by pointing --config at your own YAML.
    The bundled config.yaml is the documented starting point.

    Examples:\n
      daily-spark\n
      daily-spark --voice trailer\n
      daily-spark --voice random\n
      daily-spark --beats\n
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
    else:
        genres = all_genres

    voice_map = _assign_voices(genres, voice, voices)
    voice_name_map = {v: n for n, v in voices.items()}
    assigned_voice_names = {k: voice_name_map.get(voice_map[k], voice) for k in genres}

    click.echo(f"  Generating {len(genres)} prompt(s) via GitHub Models ({model})...\n", err=True)

    result = _generate_prompts(genres, model, writer_profile, voice_map, include_beats=beats)

    prompts = {k: v["prompt"] for k, v in result.items()}
    beats_map = {k: v.get("beats", []) for k, v in result.items()} if beats else {}

    if not prompts:
        click.echo("No prompts generated. Check your GITHUB_TOKEN.", err=True)
        sys.exit(1)

    html = render_email(prompts, genres, assigned_voice_names, beats_map)

    if print_html:
        click.echo(html)
        return

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(html, encoding="utf-8")
        click.echo(f"  Written to {output}", err=True)
        return

    for key, p in prompts.items():
        g = genres[key]
        vname = assigned_voice_names.get(key, voice)
        click.echo(f"  {g['icon']}  {g['label']}  [{vname}]")
        click.echo(f"  {p}")
        if beats_map.get(key):
            for i, beat in enumerate(beats_map[key], 1):
                click.echo(f"    {i}. {beat}")
        click.echo("")

    if email:
        click.echo("  Sending email...", err=True)
        send(html)
        click.echo("  Done.", err=True)


def _generate_prompts(
    genres: dict,
    model: str,
    writer_profile: dict | None = None,
    voice_map: dict[str, str] | None = None,
    include_beats: bool = False,
) -> dict[str, dict]:
    """Call GitHub Models and return {genre_key: {prompt, beats}} dicts."""
    client = _github_client()

    genre_lines = []
    for key, g in genres.items():
        voice_instruction = (voice_map or {}).get(key, "")
        voice_note = f" Voice style: {voice_instruction}" if voice_instruction else ""
        genre_lines.append(f'- "{key}": {g["label"]} — {g["preferences"]}{voice_note}')
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

    if include_beats:
        response_shape = (
            "{\n"
            + ",\n".join(
                f'  "{k}": {{"prompt": "prompt text here", "beats": ["beat 1", "beat 2", "beat 3", "beat 4", "beat 5", "beat 6"]}}'
                for k in genres
            )
            + "\n}"
        )
        beats_instruction = (
            "For each genre also provide 6-7 high-level plot beats — the skeleton of a story "
            "that could grow from the prompt. Beats should be one punchy sentence each, "
            "specific enough to be useful but loose enough to leave room. "
            "Label them only by number, no headers.\n\n"
        )
    else:
        response_shape = (
            "{\n"
            + ",\n".join(f'  "{k}": {{"prompt": "prompt text here", "beats": []}}' for k in genres)
            + "\n}"
        )
        beats_instruction = ""

    prompt = (
        "You are a creative writing spark generator. Your job is to produce specific, "
        "evocative writing prompts — not themes or topics, but *situations*. "
        "Each prompt should place a character in a specific moment of tension or discovery "
        "with a vivid setting detail, leaving open space for the writer to go anywhere. "
        "2-3 sentences max. No generic advice. No 'write a story about'. Just the spark. "
        "Apply the voice style instruction for each genre exactly as described.\n\n"
        f"{beats_instruction}"
        f"{profile_block}\n\n"
        f"Generate one prompt for each of these genres:\n{genre_list}\n\n"
        "Respond with JSON only — no explanation, no markdown:\n"
        f"{response_shape}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=1200 if include_beats else 800,
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

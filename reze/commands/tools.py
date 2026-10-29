"""
Everyday tools: weather, github, tts, url (upload).

Network calls go through ``reze.core.http`` (HTTPS only, size and time bounded).
"""

import asyncio
import os
import re

from reze.command_router import CommandContext, router
from reze.core import http
from reze.exceptions import MediaError
from reze.logging_config import logger
from reze.ui import ascii

CATEGORY = "Tools"

WMO = {
    0: "Clear sky", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Rain showers", 82: "Violent showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, heavy hail",
}
GH_RE = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))(?:/([A-Za-z0-9._-]{1,100}))?/?(?:\.git)?$")
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
UPLOAD_URL = "https://catbox.moe/user/api.php"


def describe_weather(code: int) -> str:
    return WMO.get(int(code), f"Code {code}")


def parse_github(text: str):
    """``owner`` or ``owner/repo`` (also accepts github.com URLs). Returns a tuple or None."""
    match = GH_RE.match((text or "").strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def split_tts_args(args):
    """Optional leading language code: ``fa Salam`` / ``en-GB hello``. Returns (lang, text)."""
    if len(args) >= 2 and LANG_RE.match(args[0]):
        return args[0], " ".join(args[1:])
    return "en", " ".join(args)


# ---------------------------------------------------------------------- weather
@router.register(
    name="weather", category=CATEGORY, cooldown=3,
    description="Current weather and today's range for a city (Open-Meteo).",
    usage=".weather <city>", examples=[".weather Tehran"],
)
async def weather_cmd(ctx: CommandContext):
    city = ctx.args_text.strip()
    if not city:
        return await ctx.reply_usage("Example: .weather Tehran")
    try:
        geo = await http.get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": city[:80], "count": "1", "language": "en", "format": "json"},
            allowed=["open-meteo.com"],
        )
        places = geo.get("results") or []
        if not places:
            return await ctx.reply(ascii.warning("City not found", [f"No match for '{city[:40]}'."]))
        place = places[0]
        data = await http.get_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": str(place["latitude"]), "longitude": str(place["longitude"]),
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto", "forecast_days": "1",
            },
            allowed=["open-meteo.com"],
        )
    except http.HttpError as exc:
        return await ctx.reply(ascii.error("Weather unavailable", [str(exc)]))

    cur, day = data.get("current", {}), data.get("daily", {})

    def first(key):
        values = day.get(key) or [None]
        return values[0]

    where = ", ".join(p for p in (place.get("name"), place.get("admin1"), place.get("country")) if p)
    lines = [
        where,
        f"{describe_weather(cur.get('weather_code', 0))}",
        f"Temperature: {cur.get('temperature_2m')} C (feels {cur.get('apparent_temperature')} C)",
        f"Humidity: {cur.get('relative_humidity_2m')}%   Wind: {cur.get('wind_speed_10m')} km/h",
        f"Today: {first('temperature_2m_min')} .. {first('temperature_2m_max')} C   Rain chance: {first('precipitation_probability_max')}%",
    ]
    return await ctx.reply(ascii.frame("Weather", lines))


# ----------------------------------------------------------------------- github
@router.register(
    name="github", category=CATEGORY, cooldown=3,
    description="Information about a GitHub repository or user.",
    usage=".github <owner/repo | owner | url>", examples=[".github UnchartedAli/Reze"],
)
async def github_cmd(ctx: CommandContext):
    parsed = parse_github(ctx.args[0] if ctx.args else "")
    if not parsed:
        return await ctx.reply_usage("Example: .github UnchartedAli/Reze")
    owner, repo = parsed
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("REZE_GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{owner}/{repo}" if repo else f"https://api.github.com/users/{owner}"
    try:
        data = await http.get_json(url, headers=headers, allowed=["api.github.com"])
    except http.HttpError as exc:
        text = str(exc)
        if "404" in text:
            return await ctx.reply(ascii.warning("Not found", [f"{owner}/{repo}" if repo else owner]))
        return await ctx.reply(ascii.error("GitHub unavailable", [text]))

    if repo:
        lines = [
            data.get("full_name", ""), (data.get("description") or "No description")[:160], "",
            f"Stars: {data.get('stargazers_count')}   Forks: {data.get('forks_count')}   Issues: {data.get('open_issues_count')}",
            f"Language: {data.get('language') or '-'}   License: {(data.get('license') or {}).get('spdx_id') or '-'}",
            f"Updated: {(data.get('pushed_at') or '')[:10]}",
            data.get("html_url", ""),
        ]
        title = "Repository"
    else:
        lines = [
            f"{data.get('name') or data.get('login')} (@{data.get('login')})", (data.get("bio") or "")[:160], "",
            f"Repos: {data.get('public_repos')}   Followers: {data.get('followers')}   Following: {data.get('following')}",
            data.get("html_url", ""),
        ]
        title = "GitHub user"
    return await ctx.reply(ascii.frame(title, [l for l in lines if l is not None]))


# -------------------------------------------------------------------------- tts
@router.register(
    name="tts", category=CATEGORY, cooldown=5,
    description="Turn text into a voice message (gTTS; the text is sent to Google).",
    usage=".tts [lang] <text>   or reply to a message", examples=[".tts en Hello there", ".tts fa Salam"],
)
async def tts_cmd(ctx: CommandContext):
    from reze.media import ffmpeg
    from reze.media.workspace import MediaWorkspace

    lang, text = split_tts_args(ctx.args)
    reply = await ctx.get_reply_message()
    if not ctx.args and reply is not None:
        text = (getattr(reply, "text", "") or "").strip()
    text = text.strip()
    if not text:
        return await ctx.reply_usage("Example: .tts en Hello there")
    if len(text) > 500:
        return await ctx.reply(ascii.error("Text too long", ["Keep it under 500 characters."]))
    try:
        from gtts import gTTS
    except ImportError:
        return await ctx.reply(ascii.warning("gTTS is not installed", ["Install it with: pip install gTTS"]))

    workspace = MediaWorkspace("tts")
    try:
        mp3 = workspace.child("speech.mp3")
        try:
            await asyncio.to_thread(lambda: gTTS(text=text, lang=lang).save(mp3))
        except Exception as exc:  # noqa: BLE001 - network or unsupported language
            return await ctx.reply(ascii.error("Speech failed", [ascii.sanitize(str(exc))[:160]]))
        out, voice = mp3, False
        if ffmpeg.available():
            ogg = workspace.child("speech.ogg")
            try:
                await asyncio.to_thread(
                    ffmpeg.run, ["-y", "-i", mp3, "-c:a", "libopus", "-b:a", "32k", "-vbr", "on", ogg])
                if os.path.isfile(ogg):
                    out, voice = ogg, True
            except Exception as exc:  # noqa: BLE001 - fall back to the mp3
                logger.debug("opus conversion failed: %s", exc)
        await ctx.send_file(file=out, voice_note=voice, reply_to=getattr(ctx.message, "reply_to_msg_id", None))
        return None
    finally:
        workspace.cleanup()


# -------------------------------------------------------------------------- url
@router.register(
    name="url", category=CATEGORY, cooldown=10,
    description="Upload a replied file to catbox.moe and get a public link.",
    usage=".url (reply to a file)",
)
async def url_cmd(ctx: CommandContext):
    from reze.media.workspace import MediaWorkspace, download_reply_media

    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to the file you want to upload.")
    workspace = MediaWorkspace("upload")
    try:
        try:
            path = await download_reply_media(ctx, workspace)
        except MediaError as exc:
            return await ctx.reply(ascii.error("Upload failed", [str(exc)]))
        with open(path, "rb") as handle:
            content = handle.read()
        try:
            link = await http.post_multipart(
                UPLOAD_URL, {"reqtype": "fileupload"}, "fileToUpload",
                os.path.basename(path), content, allowed=["catbox.moe"],
            )
        except http.HttpError as exc:
            return await ctx.reply(ascii.error("Upload failed", [str(exc)]))
        if not link.startswith("https://"):
            return await ctx.reply(ascii.error("Upload failed", [ascii.sanitize(link)[:160] or "Unexpected answer."]))
        return await ctx.reply(ascii.success("Uploaded", [link, "Anyone with the link can open this file."]))
    finally:
        workspace.cleanup()

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox
from tkinter import font as tkfont
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk
except Exception:  # noqa: BLE001
    pystray = None
    Image = None
    ImageDraw = None
    ImageFilter = None
    ImageFont = None
    ImageOps = None
    ImageTk = None


APP_NAME = "Weather Report"
APP_SLUG = "weather-report"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TERMS_URL = "https://open-meteo.com/en/terms"
REFRESH_INTERVAL_MS = 30 * 60 * 1000
FRESH_WEATHER_MAX_AGE_MINUTES = 15
UPDATE_CHECK_DELAY_MS = 10 * 1000
DEFAULT_CITY = "Helsinki"
FORECAST_DAYS = 7
POPUP_FORECAST_DAYS = max(1, FORECAST_DAYS - 1)
RAIN_PROBABILITY_LOOKAHEAD_HOURS = 6
UPDATE_REMOTE = "origin"
UPDATE_BRANCH = "main"
PROJECT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
IS_FROZEN = bool(getattr(sys, "frozen", False))
STARTUP_TARGET_PATH = (
    Path(sys.executable).resolve()
    if IS_FROZEN
    else (PROJECT_DIR / "start_weather_app.vbs").resolve()
)

def _resolve_settings_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return PROJECT_DIR

    appdata_path = Path(appdata)
    primary_dir = appdata_path / APP_SLUG
    return primary_dir


_settings_dir = _resolve_settings_dir()
try:
    _settings_dir.mkdir(parents=True, exist_ok=True)
except OSError:
    _settings_dir = PROJECT_DIR

SETTINGS_PATH = _settings_dir / "weather_settings.json"
ASSETS_DIR = RUNTIME_DIR / "assets"
APP_ICON_PATH = ASSETS_DIR / "app.ico"
APP_LOGO_PATH = ASSETS_DIR / "logo.png"
STARTUP_SHORTCUT_NAME = f"{APP_SLUG}.lnk"
DESKTOP_SHORTCUT_NAME = f"{APP_NAME}.lnk"

DARK_BG = "#0B0E14"
SURFACE_BG = "#121722"
BORDER_COLOR = "#2A3445"
TEXT_PRIMARY = "#F4F7FB"
TEXT_MUTED = "#7F8A99"
ACCENT_BLUE = "#7FC0FF"
ACCENT_GOLD = "#FFD07A"
ACCENT_LAVENDER = "#B9ACFF"
POPUP_LAYER_BG = "#0A2431"
POPUP_INPUT_BG = "#173B49"
POPUP_CONTENT_PAD = 10
POPUP_CORNER_RADIUS = 44
POPUP_BG_OPACITY = 0.85
DEFAULT_POPUP_THEME = "petrol"
POPUP_THEMES = {
    "petrol": {
        "name": "Petroli (oletus)",
        "top": "#09485D",
        "bottom": "#04182C",
        "blob1": "#197089",
        "blob2": "#126079",
        "blob3": "#03121D",
        "blob4": "#010B14",
        "preview": "#2FA8CB",
    },
    "forest": {
        "name": "Forest",
        "top": "#1A5B4B",
        "bottom": "#0C2A22",
        "blob1": "#2E8A72",
        "blob2": "#236E5B",
        "blob3": "#102A22",
        "blob4": "#0A1B16",
        "preview": "#49B693",
    },
    "sunset": {
        "name": "Sunset",
        "top": "#8C4B2B",
        "bottom": "#2E1620",
        "blob1": "#B86A3A",
        "blob2": "#9C4B52",
        "blob3": "#351C24",
        "blob4": "#201018",
        "preview": "#F08A55",
    },
    "sand": {
        "name": "Sand",
        "top": "#6E5B3E",
        "bottom": "#2A2218",
        "blob1": "#9B8257",
        "blob2": "#7A6647",
        "blob3": "#332A1E",
        "blob4": "#201A13",
        "preview": "#D8B37B",
    },
    "graphite": {
        "name": "Graphite",
        "top": "#3C4652",
        "bottom": "#171D24",
        "blob1": "#5D6C7E",
        "blob2": "#495766",
        "blob3": "#202933",
        "blob4": "#151B22",
        "preview": "#98A7BA",
    },
    "lagoon": {
        "name": "Lagoon",
        "top": "#006E78",
        "bottom": "#04272F",
        "blob1": "#00A7B5",
        "blob2": "#0C8895",
        "blob3": "#063741",
        "blob4": "#052129",
        "preview": "#2DE8FF",
    },
    "neon": {
        "name": "Neon Lime",
        "top": "#0D6B38",
        "bottom": "#041E11",
        "blob1": "#24B35F",
        "blob2": "#1A8E4B",
        "blob3": "#0A2B18",
        "blob4": "#061A10",
        "preview": "#52F28C",
    },
    "ultraviolet": {
        "name": "Ultraviolet",
        "top": "#5A2D8A",
        "bottom": "#1E1030",
        "blob1": "#8A4BD0",
        "blob2": "#6F3CB0",
        "blob3": "#281842",
        "blob4": "#180F29",
        "preview": "#C786FF",
    },
    "lava": {
        "name": "Lava",
        "top": "#8C2E16",
        "bottom": "#2B120B",
        "blob1": "#CC4C24",
        "blob2": "#A53A1A",
        "blob3": "#3A1810",
        "blob4": "#22100B",
        "preview": "#FF7A3C",
    },
    "amber": {
        "name": "Amber",
        "top": "#866315",
        "bottom": "#2E2208",
        "blob1": "#C8941C",
        "blob2": "#A37717",
        "blob3": "#3C2C0E",
        "blob4": "#241A08",
        "preview": "#FFD04A",
    },
    "cyberpink": {
        "name": "Cyber Pink",
        "top": "#8B1F66",
        "bottom": "#2A0E24",
        "blob1": "#D63A9A",
        "blob2": "#AE2D7E",
        "blob3": "#39142F",
        "blob4": "#220C1D",
        "preview": "#FF62C0",
    },
    "midnight": {
        "name": "Midnight",
        "top": "#1F2C5E",
        "bottom": "#0A1027",
        "blob1": "#3853A8",
        "blob2": "#2E4488",
        "blob3": "#121A3D",
        "blob4": "#0B1129",
        "preview": "#78A3FF",
    },
}

DISPLAY_FONT = "Segoe UI Variable Display"
TEXT_FONT = "Segoe UI Variable Text"
SYMBOL_FONT = "Segoe UI Symbol"
EMOJI_FONT = "Segoe UI Emoji"

WEEKDAY_SHORT_FI = {
    0: "Ma",
    1: "Ti",
    2: "Ke",
    3: "To",
    4: "Pe",
    5: "La",
    6: "Su",
}

def _load_text_font(size: int):
    if ImageFont is None:
        return None

    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_symbol_font(size: int):
    if ImageFont is None:
        return None

    candidates = [
        r"C:\Windows\Fonts\seguisym.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\seguiemj.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _normalize_tray_symbol(symbol_text: str) -> str:
    symbol = (symbol_text or "").strip()
    mapping = {
        "☀": "sun",
        "☾": "moon",
        "☽": "moon",
        "🌙": "moon",
        "⛅": "partly_cloudy",
        "☁": "cloud",
        "🌫": "fog",
        "🌦": "showers",
        "🌧": "rain",
        "☂": "rain",
        "❄": "snow",
        "⛈": "thunder",
        "⚡": "thunder",
        "•": "unknown",
    }
    return mapping.get(symbol, "cloud")


def _new_tray_icon_canvas(size: int = 256):
    if Image is None or ImageDraw is None:
        return None
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def _finalize_tray_icon(image):
    if Image is None or ImageOps is None or image is None:
        return None

    # Uniform tray sizing: trim transparent margins, then scale so one dimension
    # reaches tray bounds while keeping aspect ratio intact.
    if "A" in image.getbands():
        alpha = image.getchannel("A").point(lambda value: 255 if value > 20 else 0)
        bbox = alpha.getbbox()
    else:
        bbox = image.getbbox()
    if bbox:
        image = image.crop(bbox)

    resampling = getattr(Image, "Resampling", Image)
    fitted = ImageOps.contain(image, (64, 64), method=resampling.LANCZOS)
    icon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    x = (64 - fitted.width) // 2
    y = (64 - fitted.height) // 2
    icon.paste(fitted, (x, y), fitted)
    return icon


def _draw_cloud_shape(draw, bbox: tuple[int, int, int, int], fill, outline, outline_width: int = 10) -> None:
    x0, y0, x1, y1 = [int(v) for v in bbox]
    w = x1 - x0
    h = y1 - y0
    draw.rounded_rectangle(
        (x0 + int(w * 0.12), y0 + int(h * 0.43), x1 - int(w * 0.08), y1 - int(h * 0.05)),
        radius=max(8, int(h * 0.24)),
        fill=fill,
        outline=outline,
        width=outline_width,
    )
    draw.ellipse(
        (x0 + int(w * 0.00), y0 + int(h * 0.30), x0 + int(w * 0.42), y1 - int(h * 0.18)),
        fill=fill,
        outline=outline,
        width=outline_width,
    )
    draw.ellipse(
        (x0 + int(w * 0.26), y0 + int(h * 0.08), x0 + int(w * 0.70), y1 - int(h * 0.20)),
        fill=fill,
        outline=outline,
        width=outline_width,
    )
    draw.ellipse(
        (x0 + int(w * 0.54), y0 + int(h * 0.22), x1, y1 - int(h * 0.16)),
        fill=fill,
        outline=outline,
        width=outline_width,
    )


def _build_tray_crescent_icon():
    if Image is None or ImageDraw is None or ImageFilter is None or ImageOps is None:
        return None

    canvas_size = 256
    crescent_mask = Image.new("L", (canvas_size, canvas_size), 0)
    crescent_draw = ImageDraw.Draw(crescent_mask)

    # Build a filled crescent by subtracting a shifted circle from a full circle.
    crescent_draw.ellipse((26, 20, 220, 214), fill=255)
    crescent_draw.ellipse((96, 34, 252, 220), fill=0)

    shadow_mask = crescent_mask.filter(ImageFilter.GaussianBlur(7))
    out = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    out.paste((10, 16, 28, 235), (0, 0), shadow_mask)
    out.paste((244, 247, 251, 255), (0, 0), crescent_mask)

    return _finalize_tray_icon(out)


def _build_tray_sun_icon():
    result = _new_tray_icon_canvas(256)
    if result is None:
        return None
    out, draw = result

    ray_dark = (40, 22, 3, 205)
    ray_light = (255, 214, 112, 255)
    rays = [
        ((128, 20), (128, 58)),
        ((128, 198), (128, 236)),
        ((20, 128), (58, 128)),
        ((198, 128), (236, 128)),
        ((47, 47), (74, 74)),
        ((182, 182), (209, 209)),
        ((47, 209), (74, 182)),
        ((182, 74), (209, 47)),
    ]
    for start, end in rays:
        draw.line((start, end), fill=ray_dark, width=22)
        draw.line((start, end), fill=ray_light, width=14)

    draw.ellipse((69, 69, 187, 187), fill=(255, 202, 88, 255), outline=(96, 53, 8, 220), width=10)
    return _finalize_tray_icon(out)


def _build_tray_cloud_icon():
    if Image is None or ImageDraw is None or ImageFont is None:
        return None

    canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    emoji_font = None
    for path in (
        r"C:\Windows\Fonts\seguiemj.ttf",
        r"C:\Windows\Fonts\seguisym.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ):
        try:
            emoji_font = ImageFont.truetype(path, 900)
            break
        except OSError:
            continue
    if emoji_font is None:
        return None

    draw.text(
        (44, 44),
        "☁",
        font=emoji_font,
        fill=(234, 241, 252, 255),
        stroke_width=28,
        stroke_fill=(70, 89, 118, 225),
    )

    return _finalize_tray_icon(canvas)


def _build_tray_partly_cloudy_icon():
    result = _new_tray_icon_canvas(256)
    if result is None:
        return None
    out, draw = result

    rays = [
        ((104, 22), (104, 48)),
        ((104, 126), (104, 154)),
        ((54, 88), (80, 88)),
        ((128, 88), (156, 88)),
        ((68, 52), (86, 70)),
        ((122, 106), (140, 124)),
        ((68, 124), (86, 106)),
        ((122, 70), (140, 52)),
    ]
    for start, end in rays:
        draw.line((start, end), fill=(45, 24, 4, 180), width=16)
        draw.line((start, end), fill=(255, 209, 105, 255), width=10)
    draw.ellipse((48, 34, 160, 146), fill=(255, 200, 86, 255), outline=(110, 62, 9, 205), width=10)

    _draw_cloud_shape(draw, (34, 92, 252, 246), fill=(14, 24, 40, 205), outline=None, outline_width=0)
    _draw_cloud_shape(draw, (26, 84, 244, 238), fill=(232, 238, 248, 255), outline=(70, 88, 116, 215), outline_width=9)
    return _finalize_tray_icon(out)


def _build_tray_rain_icon():
    result = _new_tray_icon_canvas(256)
    if result is None:
        return None
    out, draw = result
    _draw_cloud_shape(draw, (48, 60, 220, 186), fill=(18, 29, 48, 205), outline=None, outline_width=0)
    _draw_cloud_shape(draw, (42, 52, 214, 178), fill=(222, 231, 245, 255), outline=(69, 89, 120, 220), outline_width=8)

    drops = [
        ((88, 168), (72, 220)),
        ((128, 170), (112, 224)),
        ((168, 168), (152, 220)),
    ]
    for start, end in drops:
        draw.line((start, end), fill=(21, 45, 76, 205), width=16)
        draw.line((start, end), fill=(123, 196, 255, 255), width=10)
    return _finalize_tray_icon(out)


def _build_tray_showers_icon():
    result = _new_tray_icon_canvas(256)
    if result is None:
        return None
    out, draw = result

    rays = [
        ((94, 38), (94, 58)),
        ((94, 124), (94, 145)),
        ((52, 82), (71, 82)),
        ((116, 82), (137, 82)),
        ((63, 51), (77, 65)),
        ((111, 99), (125, 113)),
        ((63, 113), (77, 99)),
        ((111, 65), (125, 51)),
    ]
    for start, end in rays:
        draw.line((start, end), fill=(45, 24, 4, 180), width=14)
        draw.line((start, end), fill=(255, 209, 105, 255), width=8)
    draw.ellipse((56, 44, 132, 120), fill=(255, 200, 86, 255), outline=(110, 62, 9, 205), width=8)

    _draw_cloud_shape(draw, (54, 86, 224, 216), fill=(14, 24, 40, 205), outline=None, outline_width=0)
    _draw_cloud_shape(draw, (48, 78, 218, 208), fill=(232, 238, 248, 255), outline=(70, 88, 116, 215), outline_width=8)

    drops = [
        ((118, 176), (104, 220)),
        ((154, 176), (140, 220)),
    ]
    for start, end in drops:
        draw.line((start, end), fill=(16, 41, 72, 205), width=14)
        draw.line((start, end), fill=(117, 190, 251, 255), width=8)
    return _finalize_tray_icon(out)


def _build_tray_fog_icon():
    result = _new_tray_icon_canvas(256)
    if result is None:
        return None
    out, draw = result
    _draw_cloud_shape(draw, (50, 64, 222, 186), fill=(19, 31, 52, 200), outline=None, outline_width=0)
    _draw_cloud_shape(draw, (44, 56, 216, 178), fill=(218, 226, 240, 255), outline=(74, 93, 121, 220), outline_width=8)

    fog_lines = [
        (56, 182, 214, 182),
        (42, 208, 196, 208),
    ]
    for line in fog_lines:
        draw.line(line, fill=(25, 44, 70, 195), width=16)
        draw.line(line, fill=(184, 201, 224, 255), width=10)
    return _finalize_tray_icon(out)


def _build_tray_snow_icon():
    result = _new_tray_icon_canvas(256)
    if result is None:
        return None
    out, draw = result
    _draw_cloud_shape(draw, (48, 60, 220, 186), fill=(18, 29, 48, 205), outline=None, outline_width=0)
    _draw_cloud_shape(draw, (42, 52, 214, 178), fill=(226, 235, 248, 255), outline=(71, 90, 119, 220), outline_width=8)

    flakes = [(88, 202), (128, 214), (168, 202)]
    for cx, cy in flakes:
        draw.line((cx - 13, cy, cx + 13, cy), fill=(17, 38, 66, 200), width=8)
        draw.line((cx, cy - 13, cx, cy + 13), fill=(17, 38, 66, 200), width=8)
        draw.line((cx - 9, cy - 9, cx + 9, cy + 9), fill=(17, 38, 66, 200), width=8)
        draw.line((cx - 9, cy + 9, cx + 9, cy - 9), fill=(17, 38, 66, 200), width=8)
        draw.line((cx - 13, cy, cx + 13, cy), fill=(186, 232, 255, 255), width=4)
        draw.line((cx, cy - 13, cx, cy + 13), fill=(186, 232, 255, 255), width=4)
        draw.line((cx - 9, cy - 9, cx + 9, cy + 9), fill=(186, 232, 255, 255), width=4)
        draw.line((cx - 9, cy + 9, cx + 9, cy - 9), fill=(186, 232, 255, 255), width=4)
    return _finalize_tray_icon(out)


def _build_tray_thunder_icon():
    result = _new_tray_icon_canvas(256)
    if result is None:
        return None
    out, draw = result
    _draw_cloud_shape(draw, (48, 54, 220, 180), fill=(17, 28, 47, 205), outline=None, outline_width=0)
    _draw_cloud_shape(draw, (42, 46, 214, 172), fill=(223, 232, 246, 255), outline=(71, 90, 119, 220), outline_width=8)

    bolt = [
        (133, 162),
        (104, 214),
        (132, 214),
        (116, 248),
        (166, 190),
        (136, 190),
        (152, 162),
    ]
    draw.polygon(bolt, fill=(46, 30, 5, 215))
    draw.polygon([(x - 2, y - 3) for x, y in bolt], fill=(255, 211, 97, 255))
    return _finalize_tray_icon(out)


def _build_tray_unknown_icon():
    result = _new_tray_icon_canvas(256)
    if result is None:
        return None
    out, draw = result
    draw.ellipse((98, 98, 158, 158), fill=(238, 243, 252, 255), outline=(80, 95, 122, 210), width=8)
    return _finalize_tray_icon(out)


def build_tray_symbol_icon(symbol_text: str):
    if Image is None or ImageDraw is None or ImageOps is None:
        return None

    symbol = _normalize_tray_symbol(symbol_text)
    builders = {
        "sun": _build_tray_sun_icon,
        "moon": _build_tray_crescent_icon,
        "partly_cloudy": _build_tray_partly_cloudy_icon,
        "cloud": _build_tray_cloud_icon,
        "fog": _build_tray_fog_icon,
        "showers": _build_tray_showers_icon,
        "rain": _build_tray_rain_icon,
        "snow": _build_tray_snow_icon,
        "thunder": _build_tray_thunder_icon,
        "unknown": _build_tray_unknown_icon,
    }
    builder = builders.get(symbol)
    if builder:
        custom_icon = builder()
        if custom_icon is not None:
            return custom_icon

    fallback_symbol = {
        "sun": "☀",
        "moon": "🌙",
        "partly_cloudy": "⛅",
        "cloud": "☁",
        "fog": "☁",
        "showers": "☂",
        "rain": "☂",
        "snow": "❄",
        "thunder": "⚡",
        "unknown": "•",
    }.get(symbol, "☁")

    canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    symbol_font = _load_symbol_font(860)
    if symbol_font is None:
        return Image.new("RGBA", (64, 64), (0, 0, 0, 0))

    draw.text(
        (24, 24),
        fallback_symbol,
        font=symbol_font,
        fill=(244, 247, 251, 255),
        stroke_width=24,
        stroke_fill=(10, 16, 28, 235),
    )

    fallback_icon = _finalize_tray_icon(canvas)
    if fallback_icon is not None:
        return fallback_icon
    return Image.new("RGBA", (64, 64), (0, 0, 0, 0))


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = (color or "").strip().lstrip("#")
    if len(value) != 6:
        return (0, 0, 0)
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def build_popup_background_image(width: int, height: int, theme: dict, radius: int = 44):
    if Image is None or ImageDraw is None or ImageFilter is None or ImageTk is None:
        return None

    width = max(1, width)
    height = max(1, height)
    resampling = getattr(Image, "Resampling", Image)
    scale = 4
    small_w = max(1, width // scale)
    small_h = max(1, height // scale)

    top_r, top_g, top_b = _hex_to_rgb(theme.get("top", "#09485D"))
    bottom_r, bottom_g, bottom_b = _hex_to_rgb(theme.get("bottom", "#04182C"))
    blob1 = _hex_to_rgb(theme.get("blob1", "#197089"))
    blob2 = _hex_to_rgb(theme.get("blob2", "#126079"))
    blob3 = _hex_to_rgb(theme.get("blob3", "#03121D"))
    blob4 = _hex_to_rgb(theme.get("blob4", "#010B14"))

    base = Image.new("RGBA", (small_w, small_h), (top_r, top_g, top_b, 255))
    draw = ImageDraw.Draw(base)

    for y in range(small_h):
        t = y / max(1, small_h - 1)
        r = int(top_r + (bottom_r - top_r) * t)
        g = int(top_g + (bottom_g - top_g) * t)
        b = int(top_b + (bottom_b - top_b) * t)
        draw.line((0, y, small_w, y), fill=(r, g, b, 255))

    draw.ellipse((-small_w * 0.20, -small_h * 0.10, small_w * 0.42, small_h * 1.10), fill=(*blob1, 170))
    draw.ellipse((small_w * 0.70, small_h * 0.32, small_w * 1.22, small_h * 1.08), fill=(*blob2, 155))
    draw.ellipse((-small_w * 0.04, small_h * 0.56, small_w * 1.12, small_h * 1.26), fill=(*blob3, 210))
    draw.ellipse((small_w * 0.12, -small_h * 0.14, small_w * 1.04, small_h * 0.72), fill=(*blob4, 175))

    blurred = base.filter(ImageFilter.GaussianBlur(radius=max(4, small_w // 14)))
    full = blurred.resize((width, height), resampling.LANCZOS)
    if POPUP_BG_OPACITY < 1.0:
        alpha = full.getchannel("A").point(lambda value: int(value * POPUP_BG_OPACITY))
        full.putalpha(alpha)
    return ImageTk.PhotoImage(full)


def build_humidity_fog_icon(width: int = 16, height: int = 14):
    if Image is None or ImageDraw is None or ImageTk is None:
        return None

    scale = 4
    w = max(1, width * scale)
    h = max(1, height * scale)
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    color = (140, 199, 255, 255)
    segments = [
        (8, 2, w - 2, 7),
        (2, 11, w - 22, 16),
        (w - 18, 11, w - 2, 16),
        (8, 20, w - 2, 25),
        (2, 29, w - 28, 34),
        (w - 24, 29, w - 2, 34),
        (8, 38, w - 2, 43),
    ]
    radius = 4
    for x0, y0, x1, y1 in segments:
        draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=color)

    resampling = getattr(Image, "Resampling", Image)
    resized = image.resize((width, height), resampling.LANCZOS)
    return ImageTk.PhotoImage(resized)


def build_rain_probability_drop_icon(width: int = 12, height: int = 12):
    if Image is None or ImageDraw is None or ImageTk is None:
        return None

    scale = 4
    w = max(1, width * scale)
    h = max(1, height * scale)
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    color = (140, 199, 255, 255)
    shadow = (15, 33, 54, 110)
    # Longer and rounder teardrop profile: narrow upper neck, fuller lower belly.
    drop_points = [
        (int(w * 0.50), int(h * 0.00)),
        (int(w * 0.56), int(h * 0.04)),
        (int(w * 0.64), int(h * 0.11)),
        (int(w * 0.71), int(h * 0.21)),
        (int(w * 0.77), int(h * 0.34)),
        (int(w * 0.80), int(h * 0.48)),
        (int(w * 0.80), int(h * 0.61)),
        (int(w * 0.76), int(h * 0.74)),
        (int(w * 0.69), int(h * 0.85)),
        (int(w * 0.60), int(h * 0.93)),
        (int(w * 0.50), int(h * 0.97)),
        (int(w * 0.40), int(h * 0.93)),
        (int(w * 0.31), int(h * 0.85)),
        (int(w * 0.24), int(h * 0.74)),
        (int(w * 0.20), int(h * 0.61)),
        (int(w * 0.20), int(h * 0.48)),
        (int(w * 0.23), int(h * 0.34)),
        (int(w * 0.29), int(h * 0.21)),
        (int(w * 0.36), int(h * 0.11)),
        (int(w * 0.44), int(h * 0.04)),
    ]
    shadow_points = [(x + 1, y + 1) for x, y in drop_points]

    draw.polygon(shadow_points, fill=shadow)
    draw.polygon(drop_points, fill=color)
    draw.ellipse(
        (
            int(w * 0.36),
            int(h * 0.20),
            int(w * 0.50),
            int(h * 0.38),
        ),
        fill=(220, 241, 255, 85),
    )

    resampling = getattr(Image, "Resampling", Image)
    resized = image.resize((width, height), resampling.LANCZOS)
    return ImageTk.PhotoImage(resized)


def build_wind_swirl_icon(width: int = 18, height: int = 14):
    if Image is None or ImageDraw is None or ImageTk is None:
        return None

    scale = 4
    w = max(1, width * scale)
    h = max(1, height * scale)
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    color = (67, 170, 246, 255)
    stroke = max(4, int(h * 0.14))
    cap_radius = max(2, stroke // 2)

    def draw_trail(x0: int, x1: int, y: int) -> None:
        draw.rounded_rectangle((x0, y - cap_radius, x1, y + cap_radius), radius=cap_radius, fill=color)

    # Cleaner swirl: fewer overlaps, more breathing room between trails.
    top_y = int(h * 0.27)
    mid_y = int(h * 0.61)
    low_y = int(h * 0.86)

    draw_trail(int(w * 0.10), int(w * 0.56), top_y)
    draw.arc(
        (int(w * 0.45), int(h * 0.04), int(w * 0.88), int(h * 0.50)),
        start=198,
        end=26,
        fill=color,
        width=stroke,
    )

    draw_trail(int(w * 0.03), int(w * 0.77), mid_y)
    draw.arc(
        (int(w * 0.63), int(h * 0.36), int(w * 1.02), int(h * 0.88)),
        start=198,
        end=24,
        fill=color,
        width=stroke,
    )

    draw_trail(int(w * 0.12), int(w * 0.39), low_y)
    draw.arc(
        (int(w * 0.23), int(h * 0.62), int(w * 0.63), int(h * 1.09)),
        start=198,
        end=24,
        fill=color,
        width=stroke,
    )

    resampling = getattr(Image, "Resampling", Image)
    resized = image.resize((width, height), resampling.LANCZOS)
    return ImageTk.PhotoImage(resized)


def format_clock_fi(value: datetime) -> str:
    day_short = WEEKDAY_SHORT_FI.get(value.weekday(), "")
    return f"{day_short} {value:%d.%m.%Y %H:%M:%S}"

def load_settings() -> dict:
    defaults = {
        "city": DEFAULT_CITY,
        "temperature_unit": "celsius",
        "popup_theme": DEFAULT_POPUP_THEME,
    }

    if not SETTINGS_PATH.exists():
        return defaults

    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return defaults

    if not isinstance(saved, dict):
        return defaults

    defaults.update(saved)
    return defaults


def save_settings(settings: dict) -> None:
    try:
        with SETTINGS_PATH.open("w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
    except OSError:
        pass


def _get_json(url: str, params: dict) -> dict:
    query = urlencode(params)
    with urlopen(f"{url}?{query}", timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def geocode_city(city_name: str) -> dict:
    payload = _get_json(
        GEOCODING_URL,
        {
            "name": city_name,
            "count": 1,
            "language": "fi",
            "format": "json",
        },
    )
    results = payload.get("results", [])
    if not results:
        raise ValueError("Paikkakuntaa ei löytynyt.")
    return results[0]


def get_weather(latitude: float, longitude: float, temperature_unit: str = "celsius") -> dict:
    return _get_json(
        FORECAST_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "temperature_unit": temperature_unit,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "weather_code",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "precipitation",
                    "is_day",
                ]
            ),
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_probability_max",
                    "precipitation_sum",
                    "sunrise",
                    "sunset",
                ]
            ),
            "hourly": "precipitation_probability",
            "wind_speed_unit": "ms",
            "timezone": "auto",
            "forecast_days": FORECAST_DAYS,
        },
    )


def resolve_weather_style(code: int | None, is_day: bool = True) -> dict:
    if code == 0:
        return {"icon": "☀" if is_day else "🌙", "label": "Selkeää", "accent": ACCENT_GOLD}
    if code in {1, 2}:
        return {"icon": "⛅", "label": "Puolipilvistä", "accent": "#E9C37A"}
    if code == 3:
        return {"icon": "☁", "label": "Pilvistä", "accent": "#D6DEEA"}
    if code in {45, 48}:
        return {"icon": "🌫", "label": "Sumua", "accent": "#BCC8D7"}
    if code in {51, 53, 55, 56, 57}:
        return {"icon": "🌦", "label": "Tihkua", "accent": "#8CC7FF"}
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return {"icon": "🌧", "label": "Sadetta", "accent": ACCENT_BLUE}
    if code in {71, 73, 75, 77, 85, 86}:
        return {"icon": "❄", "label": "Lumisadetta", "accent": "#BEE9FF"}
    if code in {95, 96, 99}:
        return {"icon": "⛈", "label": "Ukkosta", "accent": ACCENT_LAVENDER}
    return {"icon": "•", "label": "Tuntematon", "accent": "#D5DAE3"}


def format_temperature(value: float | int | None, unit_symbol: str) -> str:
    if value is None:
        return f"-°{unit_symbol}"
    return f"{round(value)}°{unit_symbol}"


def format_metric(value: float | int | None, suffix: str = "", decimals: int = 0) -> str:
    if value is None:
        return "-"
    if decimals:
        return f"{value:.{decimals}f}{suffix}"
    return f"{round(value)}{suffix}"


def format_wind_direction(value: float | int | None) -> str:
    if value is None:
        return "-"

    directions = [
        "pohjoinen",
        "pohjoiskoillinen",
        "koillinen",
        "itäkoillinen",
        "itä",
        "itäkaakko",
        "kaakko",
        "eteläkaakko",
        "etelä",
        "etelälounas",
        "lounas",
        "länsilounas",
        "länsi",
        "länsiluode",
        "luode",
        "pohjoisluode",
    ]
    index = int((float(value) + 11.25) % 360 // 22.5)
    return directions[index]


def format_time_short(value: str | None) -> str:
    parsed = _parse_open_meteo_time(value)
    return parsed.strftime("%H:%M") if parsed else "-"


def _parse_open_meteo_time(value: str | None) -> datetime | None:
    if not value:
        return None

    for pattern in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


def max_precipitation_probability_next_hours(
    weather: dict,
    hours: int = RAIN_PROBABILITY_LOOKAHEAD_HOURS,
) -> int | None:
    current_time = _parse_open_meteo_time(weather.get("current", {}).get("time"))
    hourly = weather.get("hourly", {})
    times = hourly.get("time", [])
    probabilities = hourly.get("precipitation_probability", [])
    if current_time is None or not times or not probabilities:
        return None

    window_end = current_time + timedelta(hours=hours)
    values = []
    for time_text, probability in zip(times, probabilities):
        hour_time = _parse_open_meteo_time(time_text)
        if hour_time is None or probability is None:
            continue
        if current_time <= hour_time < window_end:
            values.append(probability)

    if not values:
        return None
    return round(max(values))


def format_city(place: dict) -> str:
    city = place.get("name", "-")
    admin1 = place.get("admin1")
    country = place.get("country", "-")
    return f"{city}, {admin1}" if admin1 else f"{city}, {country}"


def get_startup_shortcut_path(name: str = STARTUP_SHORTCUT_NAME) -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise OSError("APPDATA-ympäristömuuttuja puuttuu.")
    startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup_dir / name


def get_desktop_shortcut_path(name: str = DESKTOP_SHORTCUT_NAME) -> Path:
    userprofile = os.environ.get("USERPROFILE")
    if not userprofile:
        raise OSError("USERPROFILE-ympäristömuuttuja puuttuu.")
    return Path(userprofile) / "Desktop" / name


def get_startup_shortcut_paths() -> list[Path]:
    primary = get_startup_shortcut_path()
    return [primary]


def is_startup_enabled() -> bool:
    try:
        return any(path.exists() for path in get_startup_shortcut_paths())
    except OSError:
        return False


def _ps_escape(text: str) -> str:
    return text.replace("'", "''")


def _resolve_pythonw_executable() -> Path | None:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        for version in ["313", "312", "311", "310"]:
            path = Path(local_appdata) / "Programs" / "Python" / f"Python{version}" / "pythonw.exe"
            if path.exists():
                return path

    current_python = Path(sys.executable).resolve()
    sibling_pythonw = current_python.with_name("pythonw.exe")
    if sibling_pythonw.exists():
        return sibling_pythonw

    candidate = shutil.which("pythonw")
    if candidate:
        candidate_path = Path(candidate)
        if candidate_path.exists():
            return candidate_path

    return None


def _hidden_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _resolve_shortcut_target() -> tuple[str, str, str, str]:
    if IS_FROZEN:
        target_path = str(STARTUP_TARGET_PATH)
        arguments = ""
        working_dir = str(STARTUP_TARGET_PATH.parent)
        icon_source = APP_ICON_PATH if APP_ICON_PATH.exists() else STARTUP_TARGET_PATH
    else:
        pythonw_path = _resolve_pythonw_executable()
        if pythonw_path is None:
            raise FileNotFoundError("pythonw.exe ei löytynyt. Asenna Python Windowsille.")

        target_path = str(pythonw_path)
        arguments = str((PROJECT_DIR / "main.py").resolve())
        working_dir = str(PROJECT_DIR)
        icon_source = APP_ICON_PATH if APP_ICON_PATH.exists() else pythonw_path

    return target_path, arguments, working_dir, str(icon_source)


def create_windows_shortcut(shortcut_path: Path) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)

    if not STARTUP_TARGET_PATH.exists() and IS_FROZEN:
        raise FileNotFoundError(f"Käynnistyskohdetta ei löytynyt: {STARTUP_TARGET_PATH.name}")

    shell_path = shutil.which("powershell") or shutil.which("pwsh")
    if not shell_path:
        raise OSError("PowerShelliä ei löytynyt pikakuvakkeen luontiin.")

    shortcut_target = str(shortcut_path)
    target_path, arguments, working_dir, icon_path = _resolve_shortcut_target()

    script = (
        "$WshShell = New-Object -ComObject WScript.Shell; "
        f"$Shortcut = $WshShell.CreateShortcut('{_ps_escape(shortcut_target)}'); "
        f"$Shortcut.TargetPath = '{_ps_escape(target_path)}'; "
        f"$Shortcut.Arguments = '{_ps_escape(arguments)}'; "
        f"$Shortcut.WorkingDirectory = '{_ps_escape(working_dir)}'; "
        f"$Shortcut.IconLocation = '{_ps_escape(icon_path)}'; "
        "$Shortcut.Save()"
    )
    try:
        subprocess.run(
            [shell_path, "-NoProfile", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            **_hidden_subprocess_kwargs(),
        )
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or "").strip()
        raise OSError(f"Pikakuvakkeen luonti epäonnistui: {details or error}") from error


def set_startup_enabled(enabled: bool) -> None:
    shortcut_path = get_startup_shortcut_path()
    shortcut_paths = get_startup_shortcut_paths()

    if not enabled:
        for candidate in shortcut_paths:
            if candidate.exists():
                candidate.unlink()
        return

    for candidate in shortcut_paths:
        if candidate != shortcut_path and candidate.exists():
            candidate.unlink()

    create_windows_shortcut(shortcut_path)


def create_desktop_shortcut() -> Path:
    shortcut_path = get_desktop_shortcut_path()
    create_windows_shortcut(shortcut_path)
    return shortcut_path


def _run_git_command(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    git_path = shutil.which("git")
    if not git_path:
        raise FileNotFoundError("Git-komentoa ei löytynyt PATHista.")

    return subprocess.run(
        [git_path, "-C", str(PROJECT_DIR), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        **_hidden_subprocess_kwargs(),
    )


def _git_output(args: list[str], timeout: int = 30) -> str:
    result = _run_git_command(args, timeout=timeout)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(details or f"git {' '.join(args)} epäonnistui.")
    return result.stdout.strip()


def check_github_update_status() -> dict:
    if IS_FROZEN:
        return {"state": "unsupported", "message": "Automaattinen Git-päivitys toimii lähdekoodiasennuksessa."}

    inside_worktree = _git_output(["rev-parse", "--is-inside-work-tree"])
    if inside_worktree.lower() != "true":
        return {"state": "unsupported", "message": "Sovelluskansio ei ole Git-repositorio."}

    status = _git_output(["status", "--porcelain"])
    if status:
        return {"state": "dirty", "message": "Paikallisia muutoksia on auki, päivitystä ei tehdä automaattisesti."}

    _git_output(["fetch", UPDATE_REMOTE, UPDATE_BRANCH], timeout=60)
    local_sha = _git_output(["rev-parse", "HEAD"])
    remote_ref = f"{UPDATE_REMOTE}/{UPDATE_BRANCH}"
    remote_sha = _git_output(["rev-parse", remote_ref])
    if local_sha == remote_sha:
        return {"state": "current", "message": "Sovellus on ajan tasalla."}

    ancestor = _run_git_command(["merge-base", "--is-ancestor", "HEAD", remote_ref])
    if ancestor.returncode == 0:
        return {"state": "available", "local": local_sha, "remote": remote_sha}

    return {
        "state": "diverged",
        "message": "Paikallinen ja GitHubin versio ovat eronneet; automaattinen päivitys ohitetaan.",
    }


def apply_github_update() -> None:
    result = _run_git_command(["pull", "--ff-only", UPDATE_REMOTE, UPDATE_BRANCH], timeout=120)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(details or "GitHub-päivitys epäonnistui.")


def restart_application() -> None:
    if IS_FROZEN:
        args = [str(Path(sys.executable).resolve())]
    else:
        executable = Path(sys.executable).resolve()
        if executable.name.lower() == "python.exe":
            sibling_pythonw = executable.with_name("pythonw.exe")
            if sibling_pythonw.exists():
                executable = sibling_pythonw
        args = [str(executable), str((PROJECT_DIR / "main.py").resolve())]

    subprocess.Popen(  # noqa: S603
        args,
        cwd=str(PROJECT_DIR),
        close_fds=True,
        **_hidden_subprocess_kwargs(),
    )


class WeatherWidget(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.settings = load_settings()
        self.unit_symbol = "C" if self.settings.get("temperature_unit") == "celsius" else "F"
        self.city_var = tk.StringVar(value=self.settings.get("city", DEFAULT_CITY))
        self.detail_city_var = tk.StringVar(value=self.city_var.get())
        self.status_var = tk.StringVar(value="Päivitetään säätä...")
        self.clock_var = tk.StringVar(value="--")
        self.startup_var = tk.BooleanVar(value=is_startup_enabled())
        initial_theme_id = self.settings.get("popup_theme", DEFAULT_POPUP_THEME)
        self.popup_theme_id = self._resolve_popup_theme_id(initial_theme_id)
        self.settings["popup_theme"] = self.popup_theme_id
        if initial_theme_id != self.popup_theme_id:
            save_settings(self.settings)
        self.fetch_in_progress = False
        self.update_check_in_progress = False
        self.refresh_job: str | None = None
        self.clock_job: str | None = None
        self.bootstrap_job: str | None = None
        self.update_job: str | None = None
        self.popup: tk.Toplevel | None = None
        self.forecast_cards: list[dict] = []
        self.latest_place: dict | None = None
        self.latest_weather: dict | None = None
        self.last_weather_update: datetime | None = None
        self.tray_icon = None
        self.tray_symbol = "☁"
        self.popup_bg_photo = None
        self.rain_prob_drop_icon_photo = build_rain_probability_drop_icon()
        self.humidity_fog_icon_photo = build_humidity_fog_icon()
        self.wind_swirl_icon_photo = build_wind_swirl_icon()
        self.popup_bg_size: tuple[int, int, str] | None = None

        self.title(APP_NAME)
        self.configure(bg=DARK_BG)
        self._icon_image: tk.PhotoImage | None = None
        self._apply_app_icon()
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)

        self.withdraw()
        self._build_widget_ui()
        self._build_popup()
        self._init_tray_icon()

        self.bind("<Escape>", lambda _: self._hide_popup())
        self.after(200, self._position_widget)
        self.clock_job = self.after(300, self._tick_clock)
        self.bootstrap_job = self.after(700, self.refresh_weather)
        self.update_job = self.after(UPDATE_CHECK_DELAY_MS, self.check_for_app_update)
        self.after(1500, self._refresh_startup_shortcut_if_enabled)

    def _apply_app_icon(self) -> None:
        if APP_LOGO_PATH.exists():
            try:
                self._icon_image = tk.PhotoImage(file=str(APP_LOGO_PATH))
                self.iconphoto(True, self._icon_image)
            except tk.TclError:
                self._icon_image = None

        if APP_ICON_PATH.exists():
            try:
                self.iconbitmap(str(APP_ICON_PATH))
            except tk.TclError:
                pass

    def _init_tray_icon(self) -> None:
        if pystray is None or Image is None or ImageDraw is None or ImageOps is None:
            self.status_var.set("Tray-tuki puuttuu (pystray/pillow).")
            self.deiconify()
            return

        menu = pystray.Menu(
            pystray.MenuItem(
                "Näytä/piilota viikkonäkymä",
                lambda icon, item: self.after(0, self._toggle_popup_from_tray),
                default=True,
            ),
            pystray.MenuItem("Päivitä sää", lambda icon, item: self.after(0, self.refresh_weather)),
            pystray.MenuItem(
                "Tarkista sovelluspäivitys",
                lambda icon, item: self.after(0, lambda: self.check_for_app_update(manual=True)),
            ),
            pystray.MenuItem(
                "Käynnistä tietokoneen käynnistyessä",
                lambda icon, item: self.after(0, self._toggle_startup_from_tray),
                checked=lambda item: is_startup_enabled(),
            ),
            pystray.MenuItem(
                "Luo pikakuvake työpöydälle",
                lambda icon, item: self.after(0, self._create_desktop_shortcut_from_tray),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Lopeta", lambda icon, item: self.after(0, self._quit_from_tray)),
        )

        tray_image = build_tray_symbol_icon(self.tray_symbol)
        self.tray_icon = pystray.Icon(APP_SLUG, tray_image, APP_NAME, menu)
        self.tray_icon.run_detached()

    def _stop_tray_icon(self) -> None:
        if self.tray_icon is None:
            return

        try:
            self.tray_icon.stop()
        except Exception:  # noqa: BLE001
            pass
        self.tray_icon = None

    def _toggle_startup_from_tray(self) -> None:
        desired_state = not is_startup_enabled()
        self.startup_var.set(desired_state)
        self._toggle_startup()
        if self.tray_icon:
            self.tray_icon.update_menu()

    def _create_desktop_shortcut_from_tray(self) -> None:
        try:
            shortcut_path = create_desktop_shortcut()
        except Exception as error:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Työpöydän pikakuvakkeen luonti epäonnistui: {error}")
            return

        self.status_var.set(f"Pikakuvake luotu: {shortcut_path.name}")

    def _refresh_startup_shortcut_if_enabled(self) -> None:
        if not is_startup_enabled():
            return

        def worker() -> None:
            try:
                set_startup_enabled(True)
            except Exception:
                pass

        self._start_background_worker(worker)

    def check_for_app_update(self, manual: bool = False) -> None:
        if not manual:
            self.update_job = None

        if self.update_check_in_progress:
            if manual:
                self.status_var.set("Sovelluspäivityksen tarkistus on jo käynnissä.")
            return

        self.update_check_in_progress = True
        if manual:
            self.status_var.set("Tarkistetaan sovelluspäivitystä GitHubista...")

        def worker() -> None:
            try:
                status = check_github_update_status()
            except Exception as error:  # noqa: BLE001
                status = {"state": "error", "message": str(error)}
            self.after(0, lambda: self._handle_update_check_result(status, manual))

        self._start_background_worker(worker)

    def _handle_update_check_result(self, status: dict, manual: bool) -> None:
        self.update_check_in_progress = False
        state = status.get("state")

        if state == "available":
            should_update = messagebox.askyesno(
                APP_NAME,
                "GitHubissa on uudempi versio. Päivitetäänkö sovellus nyt ja käynnistetäänkö se uudelleen?",
            )
            if should_update:
                self._apply_app_update()
            else:
                self.status_var.set("Sovelluspäivitys ohitettiin.")
            return

        message = status.get("message", "Sovelluspäivitystä ei voitu tarkistaa.")
        if manual or state not in {"current"}:
            self.status_var.set(message)

    def _apply_app_update(self) -> None:
        self.status_var.set("Päivitetään sovellusta GitHubista...")

        def worker() -> None:
            error_text = None
            try:
                apply_github_update()
            except Exception as error:  # noqa: BLE001
                error_text = str(error)
            self.after(0, lambda: self._finish_app_update(error_text))

        self._start_background_worker(worker)

    def _finish_app_update(self, error_text: str | None) -> None:
        if error_text:
            self.status_var.set(f"Sovelluspäivitys epäonnistui: {error_text}")
            return

        self.status_var.set("Sovellus päivitetty. Käynnistetään uudelleen...")
        try:
            restart_application()
        except Exception as error:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Päivitys onnistui, mutta uudelleenkäynnistys epäonnistui: {error}")
            return
        self.after(300, self.destroy)

    def _toggle_popup_from_tray(self) -> None:
        if not self.popup:
            return

        if self.popup.winfo_viewable():
            self._hide_popup()
            return

        self._ensure_fresh_weather()
        self.popup.deiconify()
        self.popup.lift()
        self._position_popup()

    def _update_tray_symbol(self, symbol_text: str, title_text: str) -> None:
        self.tray_symbol = symbol_text
        if not self.tray_icon:
            return

        tray_image = build_tray_symbol_icon(symbol_text)
        if tray_image is not None:
            self.tray_icon.icon = tray_image
        self.tray_icon.title = title_text

    def _quit_from_tray(self) -> None:
        self.destroy()

    def _start_background_worker(self, target: Callable[[], None]) -> None:
        threading.Thread(target=target, daemon=True).start()

    def destroy(self) -> None:
        for job_name in ("clock_job", "refresh_job", "bootstrap_job", "update_job"):
            job_id = getattr(self, job_name, None)
            if job_id is None:
                continue
            try:
                self.after_cancel(job_id)
            except tk.TclError:
                pass
            setattr(self, job_name, None)

        self._stop_tray_icon()
        super().destroy()

    def _build_widget_ui(self) -> None:
        self.geometry("322x84")
        shell = tk.Frame(self, bg=DARK_BG, padx=8, pady=8)
        shell.pack(fill="both", expand=True)

        self.widget_card = tk.Frame(
            shell,
            bg=SURFACE_BG,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        self.widget_card.pack(fill="both", expand=True)
        self.widget_card.bind("<Button-1>", lambda _event: self.toggle_popup())

        left = tk.Frame(self.widget_card, bg=SURFACE_BG)
        left.pack(side="left", fill="both", expand=True)
        left.bind("<Button-1>", lambda _event: self.toggle_popup())

        pill_row = tk.Frame(left, bg=SURFACE_BG)
        pill_row.pack(anchor="w")
        pill_row.bind("<Button-1>", lambda _event: self.toggle_popup())

        self.widget_icon_label = tk.Label(
            pill_row,
            text="🌙",
            font=(EMOJI_FONT, 18),
            fg=ACCENT_GOLD,
            bg=SURFACE_BG,
        )
        self.widget_icon_label.pack(side="left")
        self.widget_icon_label.bind("<Button-1>", lambda _event: self.toggle_popup())

        self.widget_temp_label = tk.Label(
            pill_row,
            text="--°C",
            font=(DISPLAY_FONT, 22, "bold"),
            fg=TEXT_PRIMARY,
            bg=SURFACE_BG,
        )
        self.widget_temp_label.pack(side="left", padx=(10, 0))
        self.widget_temp_label.bind("<Button-1>", lambda _event: self.toggle_popup())

        self.widget_city_label = tk.Label(
            left,
            text=self.city_var.get(),
            font=(TEXT_FONT, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=SURFACE_BG,
        )
        self.widget_city_label.pack(anchor="w", pady=(4, 0))
        self.widget_city_label.bind("<Button-1>", lambda _event: self.toggle_popup())

        self.widget_condition_label = tk.Label(
            left,
            text="Napsauta avataksesi ennusteen",
            font=(TEXT_FONT, 9),
            fg=TEXT_MUTED,
            bg=SURFACE_BG,
        )
        self.widget_condition_label.pack(anchor="w", pady=(2, 0))
        self.widget_condition_label.bind("<Button-1>", lambda _event: self.toggle_popup())

        right = tk.Frame(self.widget_card, bg=SURFACE_BG)
        right.pack(side="right", anchor="n")

        self._create_icon_button(right, "⟳", self.refresh_weather).pack(side="top")
        self._create_icon_button(right, "✕", self.destroy).pack(side="top", pady=(8, 0))

    def _build_popup(self) -> None:
        self.popup = tk.Toplevel(self)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        self.popup.wm_attributes("-topmost", True)
        self.popup.configure(bg=POPUP_LAYER_BG)
        self.popup.bind("<Escape>", lambda _: self._hide_popup())

        self.popup_bg_canvas = tk.Canvas(
            self.popup,
            bg=POPUP_LAYER_BG,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.popup_bg_canvas.pack(fill="both", expand=True)

        self.clock_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="--",
            anchor="nw",
            font=(TEXT_FONT, 13, "bold"),
            fill="#EFF4FF",
        )
        self.hero_updated_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="Päivitetty --",
            anchor="nw",
            font=(TEXT_FONT, 9),
            fill="#B7C4E8",
        )
        self.location_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="Kaupunki",
            anchor="ne",
            font=(TEXT_FONT, 8, "bold"),
            fill="#B8D8E4",
        )
        self.theme_dot_item = self.popup_bg_canvas.create_text(
            0,
            0,
            text="●",
            anchor="ne",
            font=(SYMBOL_FONT, 12),
            fill="#2FA8CB",
        )
        self.popup_bg_canvas.tag_bind(self.theme_dot_item, "<Button-1>", self._cycle_popup_theme)
        self.popup_bg_canvas.tag_bind(
            self.theme_dot_item,
            "<Enter>",
            lambda _event: self.popup_bg_canvas.configure(cursor="hand2"),
        )
        self.popup_bg_canvas.tag_bind(
            self.theme_dot_item,
            "<Leave>",
            lambda _event: self.popup_bg_canvas.configure(cursor=""),
        )
        self._update_theme_dot_color()

        self.hero_city_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text=self.city_var.get(),
            anchor="nw",
            font=(TEXT_FONT, 18, "bold"),
            fill="#F3F7FF",
        )
        self.hero_icon_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="☁",
            anchor="w",
            font=(EMOJI_FONT, 42),
            fill="#F5F8FF",
        )
        self.hero_temp_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="--°C",
            anchor="nw",
            font=(DISPLAY_FONT, 54, "bold"),
            fill="#FFFFFF",
        )
        self.today_stats_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="",
            anchor="ne",
            font=(TEXT_FONT, 11),
            fill="#F2F6FF",
            justify="right",
            state="hidden",
        )
        self.today_rain_mm_icon_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="☂",
            anchor="ne",
            font=(SYMBOL_FONT, 11),
            fill="#F2F6FF",
        )
        self.today_rain_mm_value_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="-- mm",
            anchor="ne",
            font=(TEXT_FONT, 11),
            fill="#F2F6FF",
        )
        if self.rain_prob_drop_icon_photo is not None:
            self.today_rain_prob_icon_label = self.popup_bg_canvas.create_image(
                0,
                0,
                image=self.rain_prob_drop_icon_photo,
                anchor="ne",
            )
        else:
            self.today_rain_prob_icon_label = self.popup_bg_canvas.create_text(
                0,
                0,
                text="💧",
                anchor="ne",
                font=(EMOJI_FONT, 11),
                fill="#8CC7FF",
            )
        self.today_rain_prob_value_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="--%",
            anchor="ne",
            font=(TEXT_FONT, 11),
            fill="#F2F6FF",
        )
        if self.humidity_fog_icon_photo is not None:
            self.today_humidity_icon_label = self.popup_bg_canvas.create_image(
                0,
                0,
                image=self.humidity_fog_icon_photo,
                anchor="ne",
            )
        else:
            self.today_humidity_icon_label = self.popup_bg_canvas.create_text(
                0,
                0,
                text="🌫",
                anchor="ne",
                font=(SYMBOL_FONT, 11),
                fill="#8CC7FF",
            )
        self.today_humidity_value_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="--%",
            anchor="ne",
            font=(TEXT_FONT, 11),
            fill="#F2F6FF",
        )
        if self.wind_swirl_icon_photo is not None:
            self.today_wind_icon_label = self.popup_bg_canvas.create_image(
                0,
                0,
                image=self.wind_swirl_icon_photo,
                anchor="ne",
            )
        else:
            self.today_wind_icon_label = self.popup_bg_canvas.create_text(
                0,
                0,
                text="🌬",
                anchor="ne",
                font=(EMOJI_FONT, 11),
                fill="#F2F6FF",
            )
        self.today_wind_value_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="-- m/s (--)",
            anchor="ne",
            font=(TEXT_FONT, 11),
            fill="#F2F6FF",
        )
        self.today_condition_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="Keli --",
            anchor="ne",
            font=(TEXT_FONT, 20, "bold"),
            fill="#F3F7FF",
        )
        self.today_hilo_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="ylin --° / alin --°",
            anchor="ne",
            font=(TEXT_FONT, 16, "bold"),
            fill="#E3ECFF",
        )
        self.today_sun_icon_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="☀️",
            anchor="ne",
            font=(EMOJI_FONT, 11),
            fill=ACCENT_GOLD,
        )
        self.today_sunrise_time_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="--:--",
            anchor="ne",
            font=(TEXT_FONT, 11),
            fill="#CCD9F7",
        )
        self.today_moon_icon_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="🌙",
            anchor="ne",
            font=(EMOJI_FONT, 11),
            fill=ACCENT_GOLD,
        )
        self.today_sunset_time_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="--:--",
            anchor="ne",
            font=(TEXT_FONT, 11),
            fill="#CCD9F7",
        )
        self.footer_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="Säädata: Open-Meteo (CC BY 4.0) · Käyttöehdot",
            anchor="se",
            font=(TEXT_FONT, 8),
            fill="#A7B6DB",
            activefill="#D6E3FF",
        )
        self.popup_bg_canvas.tag_bind(self.footer_label, "<Button-1>", lambda _event: self._open_open_meteo_terms())
        self.popup_bg_canvas.tag_bind(
            self.footer_label,
            "<Enter>",
            lambda _event: self.popup_bg_canvas.configure(cursor="hand2"),
        )
        self.popup_bg_canvas.tag_bind(
            self.footer_label,
            "<Leave>",
            lambda _event: self.popup_bg_canvas.configure(cursor=""),
        )

        self.forecast_cards = []
        for _ in range(POPUP_FORECAST_DAYS):
            day_id = self.popup_bg_canvas.create_text(
                0,
                0,
                text="-",
                anchor="n",
                font=(TEXT_FONT, 9, "bold"),
                fill="#DDE7FF",
            )
            sun_id = self.popup_bg_canvas.create_text(
                0,
                0,
                text="☀️",
                anchor="n",
                font=(EMOJI_FONT, 14),
                fill=ACCENT_GOLD,
                state="hidden",
            )
            icon_id = self.popup_bg_canvas.create_text(
                0,
                0,
                text="•",
                anchor="n",
                font=(EMOJI_FONT, 24),
                fill="#CDE0FF",
            )
            temp_id = self.popup_bg_canvas.create_text(
                0,
                0,
                text="--° / --°",
                anchor="n",
                font=(TEXT_FONT, 11),
                fill="#F3F7FF",
            )
            self.forecast_cards.append({"day": day_id, "sun": sun_id, "icon": icon_id, "temp": temp_id})

        self.location_entry_shell = tk.Frame(
            self.popup_bg_canvas,
            bg=POPUP_INPUT_BG,
            bd=0,
            highlightthickness=0,
            padx=5,
            pady=0,
        )
        self.location_entry = tk.Entry(
            self.location_entry_shell,
            textvariable=self.detail_city_var,
            font=(TEXT_FONT, 10, "bold"),
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=POPUP_INPUT_BG,
            fg="#EAF0FF",
            insertbackground="#EEF4FF",
            justify="left",
            width=16,
        )
        self.location_entry.pack(side="left", ipady=2)
        self.location_entry.bind("<Return>", lambda _: self._search_from_popup())

        self.search_button = self._create_icon_button(self.popup_bg_canvas, "Hae", self._search_from_popup, width=4)
        self.refresh_button = self._create_icon_button(self.popup_bg_canvas, "⟳", self.refresh_weather)
        self.close_button = self._create_icon_button(self.popup_bg_canvas, "✕", self._hide_popup)


        self.location_entry_window = self.popup_bg_canvas.create_window(
            0,
            0,
            window=self.location_entry_shell,
            anchor="ne",
        )
        self.search_button_window = self.popup_bg_canvas.create_window(0, 0, window=self.search_button, anchor="ne")
        self.refresh_button_window = self.popup_bg_canvas.create_window(0, 0, window=self.refresh_button, anchor="ne")
        self.close_button_window = self.popup_bg_canvas.create_window(0, 0, window=self.close_button, anchor="ne")
        self.popup_bg_canvas.bind("<Configure>", self._on_popup_canvas_configure)
        self.popup.update_idletasks()

    def _on_popup_canvas_configure(self, event: tk.Event) -> None:
        width = max(1, event.width)
        height = max(1, event.height)
        self._apply_popup_round_corners(POPUP_CORNER_RADIUS)
        self._draw_popup_gradient(width, height)
        self._layout_popup_content(width, height)

    def _layout_popup_content(self, width: int, height: int) -> None:
        pad = POPUP_CONTENT_PAD + 8
        left_nudge = 5
        base_height = 338
        extra_height = max(0, height - base_height)

        top_shift = int(extra_height * 0.08)
        hero_shift = int(extra_height * 0.12)
        right_shift = int(extra_height * 0.10)
        forecast_shift = int(extra_height * 0.00)

        self.popup_bg_canvas.coords(self.clock_label, pad + left_nudge, 12 + top_shift)
        self.popup_bg_canvas.itemconfigure(self.clock_label, text=self.clock_var.get())
        self.popup_bg_canvas.coords(self.hero_updated_label, pad + left_nudge, 32 + top_shift)

        self.popup.update_idletasks()
        control_y = 12 + top_shift
        gap = 4
        right = width - pad

        self.popup_bg_canvas.coords(self.close_button_window, right, control_y)
        right -= self.close_button.winfo_reqwidth() + gap

        self.popup_bg_canvas.coords(self.refresh_button_window, right, control_y)
        right -= self.refresh_button.winfo_reqwidth() + gap

        self.popup_bg_canvas.coords(self.search_button_window, right, control_y)
        right -= self.search_button.winfo_reqwidth() + 6

        self.popup_bg_canvas.coords(self.location_entry_window, right, control_y)
        right -= self.location_entry_shell.winfo_reqwidth() + 8
        self.popup_bg_canvas.coords(self.location_label, right, control_y + 4)
        label_bbox = self.popup_bg_canvas.bbox(self.location_label)
        label_width = (label_bbox[2] - label_bbox[0]) if label_bbox else 56
        self.popup_bg_canvas.coords(self.theme_dot_item, right - label_width - 8, control_y + 2)

        self.popup_bg_canvas.coords(self.hero_city_label, pad + left_nudge, 57 + hero_shift)
        self.popup_bg_canvas.coords(self.hero_icon_label, pad + 8 + left_nudge, 137 + hero_shift)
        self.popup_bg_canvas.coords(self.hero_temp_label, pad + 92 + left_nudge, 99 + hero_shift)

        right_text = width - pad - 14
        stats_top = 61 + right_shift
        self._layout_today_stats(right_text, stats_top)
        self.popup_bg_canvas.coords(self.today_condition_label, right_text, 106 + right_shift)
        self.popup_bg_canvas.coords(self.today_hilo_label, right_text, 144 + right_shift)
        sun_row_y = 173 + right_shift
        icon_time_gap = 4
        group_gap = 16
        self.popup_bg_canvas.coords(self.today_sunset_time_label, right_text, sun_row_y)
        self.popup.update_idletasks()
        sunset_bbox = self.popup_bg_canvas.bbox(self.today_sunset_time_label)
        sunset_left = sunset_bbox[0] if sunset_bbox else (right_text - 36)

        self.popup_bg_canvas.coords(self.today_moon_icon_label, sunset_left - icon_time_gap, sun_row_y)
        self.popup.update_idletasks()
        moon_bbox = self.popup_bg_canvas.bbox(self.today_moon_icon_label)
        moon_left = moon_bbox[0] if moon_bbox else (sunset_left - 14)

        self.popup_bg_canvas.coords(self.today_sunrise_time_label, moon_left - group_gap, sun_row_y)
        self.popup.update_idletasks()
        sunrise_bbox = self.popup_bg_canvas.bbox(self.today_sunrise_time_label)
        sunrise_left = sunrise_bbox[0] if sunrise_bbox else (moon_left - 42)

        self.popup_bg_canvas.coords(self.today_sun_icon_label, sunrise_left - icon_time_gap, sun_row_y)

        forecast_top = (height - 116) - forecast_shift
        forecast_side_inset = 12
        forecast_left = pad + forecast_side_inset
        usable_width = max(1, width - (forecast_left * 2))
        col_width = usable_width / max(1, POPUP_FORECAST_DAYS)
        for index, card in enumerate(self.forecast_cards):
            center_x = int(forecast_left + (index + 0.5) * col_width)
            card["center_x"] = center_x
            card["sun_y"] = forecast_top + 15
            card["icon_y"] = forecast_top + 17
            self.popup_bg_canvas.coords(card["day"], center_x, forecast_top)
            self.popup_bg_canvas.coords(card["sun"], center_x - 8, card["sun_y"])
            self.popup_bg_canvas.coords(card["icon"], center_x, card["icon_y"])
            self.popup_bg_canvas.coords(card["temp"], center_x, forecast_top + 63)

        self.popup_bg_canvas.coords(self.footer_label, width - pad, height - 9)

    def _layout_today_stats(self, right_x: int, top_y: int) -> None:
        icon_value_gap = 4
        item_gap = 14
        top_icon_y_offset = 6
        wind_icon_y_offset = 4
        try:
            stats_font = tkfont.Font(font=(TEXT_FONT, 11))
            line_height = stats_font.metrics("linespace")
        except tk.TclError:
            line_height = 14

        # Top row: humidity (right), rain probability (middle), rain mm (left).
        self.popup_bg_canvas.coords(self.today_humidity_value_label, right_x, top_y)
        humidity_bbox = self.popup_bg_canvas.bbox(self.today_humidity_value_label)
        humidity_left = humidity_bbox[0] if humidity_bbox else (right_x - 24)
        self.popup_bg_canvas.coords(
            self.today_humidity_icon_label,
            humidity_left - icon_value_gap,
            top_y + top_icon_y_offset,
        )
        humidity_icon_bbox = self.popup_bg_canvas.bbox(self.today_humidity_icon_label)
        cursor = (humidity_icon_bbox[0] if humidity_icon_bbox else (humidity_left - 14)) - item_gap

        self.popup_bg_canvas.coords(self.today_rain_prob_value_label, cursor, top_y)
        rain_prob_bbox = self.popup_bg_canvas.bbox(self.today_rain_prob_value_label)
        rain_prob_left = rain_prob_bbox[0] if rain_prob_bbox else (cursor - 20)
        self.popup_bg_canvas.coords(
            self.today_rain_prob_icon_label,
            rain_prob_left - icon_value_gap,
            top_y + top_icon_y_offset,
        )
        rain_prob_icon_bbox = self.popup_bg_canvas.bbox(self.today_rain_prob_icon_label)
        cursor = (rain_prob_icon_bbox[0] if rain_prob_icon_bbox else (rain_prob_left - 12)) - item_gap

        self.popup_bg_canvas.coords(self.today_rain_mm_value_label, cursor, top_y)
        rain_mm_bbox = self.popup_bg_canvas.bbox(self.today_rain_mm_value_label)
        rain_mm_left = rain_mm_bbox[0] if rain_mm_bbox else (cursor - 42)
        self.popup_bg_canvas.coords(self.today_rain_mm_icon_label, rain_mm_left - icon_value_gap, top_y)

        # Second row: wind.
        wind_y = top_y + line_height + 2
        self.popup_bg_canvas.coords(self.today_wind_value_label, right_x, wind_y)
        wind_bbox = self.popup_bg_canvas.bbox(self.today_wind_value_label)
        wind_left = wind_bbox[0] if wind_bbox else (right_x - 72)
        self.popup_bg_canvas.coords(self.today_wind_icon_label, wind_left - icon_value_gap, wind_y + wind_icon_y_offset)

    def _draw_popup_gradient(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return

        theme = self._current_popup_theme()
        cache_key = (width, height, self.popup_theme_id)
        if self.popup_bg_size == cache_key:
            return

        self.popup_bg_size = cache_key
        self.popup_bg_canvas.delete("grad")
        self.popup_bg_photo = build_popup_background_image(width, height, theme=theme, radius=POPUP_CORNER_RADIUS)
        if self.popup_bg_photo is not None:
            self.popup_bg_canvas.create_image(0, 0, anchor="nw", image=self.popup_bg_photo, tags="grad")
            self.popup_bg_canvas.tag_lower("grad")

    def _apply_popup_round_corners(self, radius: int = POPUP_CORNER_RADIUS) -> None:
        if not self.popup or os.name != "nt":
            return

        try:
            import ctypes

            width = max(1, self.popup.winfo_width())
            height = max(1, self.popup.winfo_height())
            hwnd = self.popup.winfo_id()

            region = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius, radius)
            if region and not ctypes.windll.user32.SetWindowRgn(hwnd, region, True):
                ctypes.windll.gdi32.DeleteObject(region)
        except Exception:
            pass

    def _create_icon_button(self, parent: tk.Widget, text: str, command, width: int = 2) -> tk.Button:
        font_family = TEXT_FONT if len(text) > 1 else SYMBOL_FONT
        parent_bg = parent.cget("bg")
        button_bg = POPUP_INPUT_BG if parent_bg == POPUP_LAYER_BG else "#202837"
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=(font_family, 9),
            bd=0,
            relief="flat",
            cursor="hand2",
            bg=button_bg,
            fg="#EEF4FF",
            activebackground=button_bg,
            activeforeground="#FFFFFF",
            width=width,
            padx=0,
            pady=2,
        )

    def _position_widget(self) -> None:
        self.update_idletasks()
        width = 322
        height = 84
        x_pos = self.winfo_screenwidth() - width - 20
        y_pos = self.winfo_screenheight() - height - 70
        self.geometry(f"{width}x{height}+{x_pos}+{y_pos}")
        if self.popup and self.popup.winfo_viewable():
            self._position_popup()

    def _position_popup(self) -> None:
        if not self.popup:
            return

        self.popup.update_idletasks()
        popup_width = 584
        popup_height = 329

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        left, top, right, bottom = 0, 0, screen_w, screen_h

        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass

        available_width = max(420, right - left - 10)
        popup_width = min(popup_width, available_width)

        available_height = max(260, bottom - top - 10)
        popup_height = min(popup_height, available_height)

        x_pos = max(left + 5, right - popup_width - 5)

        if bottom < screen_h:
            y_pos = max(0, bottom - popup_height - 3)
        elif top > 0:
            y_pos = top + 3
        else:
            y_pos = max(0, bottom - popup_height - 3)

        self.popup.geometry(f"{popup_width}x{popup_height}+{x_pos}+{y_pos}")
        self.popup.update_idletasks()
        self._apply_popup_round_corners(POPUP_CORNER_RADIUS)

    def _tick_clock(self) -> None:
        self.clock_var.set(format_clock_fi(datetime.now()))
        if hasattr(self, "popup_bg_canvas") and hasattr(self, "clock_label"):
            self.popup_bg_canvas.itemconfigure(self.clock_label, text=self.clock_var.get())
        self.clock_job = self.after(1000, self._tick_clock)

    def toggle_popup(self) -> None:
        if not self.popup:
            return

        if self.popup.winfo_viewable():
            self._hide_popup()
            return

        self._ensure_fresh_weather()
        self.popup.deiconify()
        self.popup.lift()
        self._position_popup()

    def _hide_popup(self) -> None:
        if self.popup:
            self.popup.withdraw()

    def _ensure_fresh_weather(self) -> None:
        if self.fetch_in_progress:
            return

        if self.latest_weather is None or self.last_weather_update is None:
            self.refresh_weather()
            return

        if datetime.now() - self.last_weather_update > timedelta(minutes=FRESH_WEATHER_MAX_AGE_MINUTES):
            self.refresh_weather()

    def _toggle_startup(self) -> None:
        desired_state = self.startup_var.get()
        try:
            set_startup_enabled(desired_state)
        except Exception as error:  # noqa: BLE001
            self.startup_var.set(not desired_state)
            messagebox.showerror(APP_NAME, f"Käynnistysasetuksen päivitys epäonnistui: {error}")
            return

        if desired_state:
            self.status_var.set("Automaattinen käynnistys päällä. Toteutus on kevyt Startup-pikakuvake.")
        else:
            self.status_var.set("Automaattinen käynnistys poistettu käytöstä.")

    def _search_from_popup(self) -> None:
        city = self.detail_city_var.get().strip()
        if not city:
            messagebox.showinfo(APP_NAME, "Kirjoita paikkakunnan nimi.")
            return

        self.city_var.set(city)
        self.refresh_weather()

    def _open_open_meteo_terms(self) -> None:
        try:
            webbrowser.open_new_tab(OPEN_METEO_TERMS_URL)
        except Exception:
            self.status_var.set("Open-Meteo-linkin avaaminen epäonnistui.")

    def _resolve_popup_theme_id(self, theme_id: str | None) -> str:
        candidate = (theme_id or "").strip().lower()
        return candidate if candidate in POPUP_THEMES else DEFAULT_POPUP_THEME

    def _current_popup_theme(self) -> dict:
        return POPUP_THEMES.get(self.popup_theme_id, POPUP_THEMES[DEFAULT_POPUP_THEME])

    def _next_popup_theme_id(self) -> str:
        theme_keys = list(POPUP_THEMES.keys())
        if not theme_keys:
            return DEFAULT_POPUP_THEME
        try:
            current_index = theme_keys.index(self.popup_theme_id)
        except ValueError:
            return theme_keys[0]
        return theme_keys[(current_index + 1) % len(theme_keys)]

    def _update_theme_dot_color(self) -> None:
        if not hasattr(self, "theme_dot_item"):
            return
        preview_theme_id = self._next_popup_theme_id()
        preview = POPUP_THEMES.get(preview_theme_id, POPUP_THEMES[DEFAULT_POPUP_THEME]).get("preview", "#2FA8CB")
        self.popup_bg_canvas.itemconfigure(self.theme_dot_item, fill=preview)

    def _set_popup_theme(self, theme_id: str) -> None:
        resolved = self._resolve_popup_theme_id(theme_id)
        if resolved == self.popup_theme_id:
            return

        self.popup_theme_id = resolved
        self.settings["popup_theme"] = resolved
        save_settings(self.settings)
        self.popup_bg_size = None
        self._update_theme_dot_color()

        if self.popup:
            width = max(1, self.popup.winfo_width())
            height = max(1, self.popup.winfo_height())
            self._draw_popup_gradient(width, height)

        self.status_var.set(f"Väriteema: {self._current_popup_theme().get('name', resolved)}")

    def _cycle_popup_theme(self, _event: tk.Event | None = None) -> None:
        self._set_popup_theme(self._next_popup_theme_id())

    def refresh_weather(self) -> None:
        if self.fetch_in_progress:
            return

        city = self.city_var.get().strip()
        if not city:
            messagebox.showinfo(APP_NAME, "Kirjoita paikkakunnan nimi.")
            return

        self.fetch_in_progress = True
        self.status_var.set(f"Haetaan säätä: {city}")
        worker = threading.Thread(target=self._fetch_worker, args=(city,), daemon=True)
        worker.start()

    def _fetch_worker(self, city: str) -> None:
        try:
            place = geocode_city(city)

            weather = None
            for attempt in range(2):
                try:
                    weather = get_weather(
                        place["latitude"],
                        place["longitude"],
                        self.settings.get("temperature_unit", "celsius"),
                    )
                    break
                except (URLError, HTTPError, TimeoutError):
                    if attempt == 1:
                        raise
                    time.sleep(1.0)

            if weather is None:
                raise RuntimeError("Säädata puuttuu palveluvastauksesta.")

            self.after(0, lambda: self._apply_weather(place, weather))
        except ValueError as error:
            self.after(0, lambda: self._show_error(str(error)))
        except (URLError, HTTPError, TimeoutError):
            self.after(0, lambda: self._show_error("Verkkovirhe. Tarkista internet-yhteys."))
        except Exception as error:  # noqa: BLE001
            self.after(0, lambda: self._show_error(f"Tuntematon virhe: {error}"))

    def _show_error(self, text: str) -> None:
        self.fetch_in_progress = False
        self.status_var.set("Päivitys epäonnistui, yritetään uudelleen 30 minuutin päästä.")
        # Keep the last successful weather symbol in tray after transient fetch errors.
        # Show the bullet only when we do not have any weather data yet.
        if self.latest_weather:
            current = self.latest_weather.get("current", {})
            style = resolve_weather_style(current.get("weather_code"), current.get("is_day", 1) == 1)
            city_text = format_city(self.latest_place) if isinstance(self.latest_place, dict) else self.city_var.get()
            current_temp = format_temperature(current.get("temperature_2m"), self.unit_symbol)
            self._update_tray_symbol(style["icon"], f"{city_text}: {current_temp} (päivitys epäonnistui)")
        else:
            self._update_tray_symbol("•", f"{APP_NAME}: päivitys epäonnistui")
        if not self.latest_weather:
            messagebox.showerror(APP_NAME, text)
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self.refresh_job is not None:
            self.after_cancel(self.refresh_job)
        self.refresh_job = self.after(REFRESH_INTERVAL_MS, self.refresh_weather)

    def _apply_weather(self, place: dict, weather: dict) -> None:
        self.fetch_in_progress = False
        self.latest_place = place
        self.latest_weather = weather
        resolved_city = place.get("name", self.city_var.get())
        if self.settings.get("city") != resolved_city:
            self.settings["city"] = resolved_city
            save_settings(self.settings)

        current = weather.get("current", {})
        daily = weather.get("daily", {})
        current_units = weather.get("current_units", {})
        daily_units = weather.get("daily_units", {})

        unit_symbol = current_units.get("temperature_2m", f"°{self.unit_symbol}").replace("°", "")
        self.unit_symbol = unit_symbol or self.unit_symbol

        style = resolve_weather_style(current.get("weather_code"), current.get("is_day", 1) == 1)
        refreshed_at = datetime.now()
        self.last_weather_update = refreshed_at
        now_text = refreshed_at.strftime("%H:%M")
        current_temp = format_temperature(current.get("temperature_2m"), self.unit_symbol)
        city_text = format_city(place)

        dates = daily.get("time", [])
        code_list = daily.get("weather_code", [])
        t_min = daily.get("temperature_2m_min", [])
        t_max = daily.get("temperature_2m_max", [])
        daily_rain_prob = daily.get("precipitation_probability_max", [])
        rain_sum = daily.get("precipitation_sum", [])
        sunrise_list = daily.get("sunrise", [])
        sunset_list = daily.get("sunset", [])

        rain_mm_unit = daily_units.get("precipitation_sum", "mm")
        today_high = format_temperature(t_max[0] if t_max else None, self.unit_symbol)
        today_low = format_temperature(t_min[0] if t_min else None, self.unit_symbol)
        humidity_pct = format_metric(current.get("relative_humidity_2m"), "%")
        next_hours_rain_prob = max_precipitation_probability_next_hours(weather)
        if next_hours_rain_prob is not None:
            today_rain_prob = f"{next_hours_rain_prob}%"
        elif daily_rain_prob:
            today_rain_prob = f"{daily_rain_prob[0]}%"
        else:
            today_rain_prob = "-"
        today_rain_mm = format_metric(rain_sum[0] if rain_sum else None, f" {rain_mm_unit}", decimals=1)
        wind_speed_ms = format_metric(current.get("wind_speed_10m"), " m/s", decimals=1)
        wind_direction = format_wind_direction(current.get("wind_direction_10m"))
        today_sunrise = format_time_short(sunrise_list[0] if sunrise_list else None)
        today_sunset = format_time_short(sunset_list[0] if sunset_list else None)

        self.widget_icon_label.config(text=style["icon"], fg=style["accent"])
        self.widget_temp_label.config(text=current_temp)
        self.widget_city_label.config(text=city_text)
        self.widget_condition_label.config(text=style["label"])

        self.popup_bg_canvas.itemconfigure(self.hero_icon_label, text=style["icon"], fill=style["accent"])
        self.popup_bg_canvas.itemconfigure(self.hero_temp_label, text=current_temp)
        self.popup_bg_canvas.itemconfigure(self.hero_city_label, text=city_text)
        self.popup_bg_canvas.itemconfigure(self.hero_updated_label, text=f"Päivitetty {now_text}")

        wind_text = f"{wind_speed_ms} ({wind_direction})"
        self.popup_bg_canvas.itemconfigure(self.today_rain_mm_value_label, text=today_rain_mm)
        self.popup_bg_canvas.itemconfigure(self.today_rain_prob_value_label, text=today_rain_prob)
        self.popup_bg_canvas.itemconfigure(self.today_humidity_value_label, text=humidity_pct)
        self.popup_bg_canvas.itemconfigure(self.today_wind_value_label, text=wind_text)
        if self.rain_prob_drop_icon_photo is None:
            self.popup_bg_canvas.itemconfigure(self.today_rain_prob_icon_label, text="💧", fill="#8CC7FF")
        else:
            self.popup_bg_canvas.itemconfigure(self.today_rain_prob_icon_label, image=self.rain_prob_drop_icon_photo)
        if self.wind_swirl_icon_photo is None:
            self.popup_bg_canvas.itemconfigure(self.today_wind_icon_label, text="🌬", fill="#F2F6FF")
        else:
            self.popup_bg_canvas.itemconfigure(self.today_wind_icon_label, image=self.wind_swirl_icon_photo)
        stats_right = self.popup_bg_canvas.coords(self.today_condition_label)
        right_x = int(stats_right[0]) if stats_right else (self.popup.winfo_width() - (POPUP_CONTENT_PAD + 22))
        stats_top = self.popup_bg_canvas.coords(self.today_rain_mm_value_label)
        top_y = int(stats_top[1]) if stats_top else 61
        self._layout_today_stats(right_x, top_y)
        self.popup_bg_canvas.itemconfigure(self.today_condition_label, text=style["label"])
        self.popup_bg_canvas.itemconfigure(self.today_hilo_label, text=f"ylin {today_high} / alin {today_low}")
        self.popup_bg_canvas.itemconfigure(self.today_sun_icon_label, text="☀️", fill=ACCENT_GOLD)
        self.popup_bg_canvas.itemconfigure(self.today_sunrise_time_label, text=today_sunrise)
        self.popup_bg_canvas.itemconfigure(self.today_moon_icon_label, text="🌙", fill=ACCENT_GOLD)
        self.popup_bg_canvas.itemconfigure(self.today_sunset_time_label, text=today_sunset)

        self.status_var.set("")
        self._update_tray_symbol(style["icon"], f"{city_text}: {current_temp} {style['label']}")
        self.detail_city_var.set(place.get("name", self.city_var.get()))
        self.startup_var.set(is_startup_enabled())

        for index, card in enumerate(self.forecast_cards):
            data_index = index + 1
            if data_index >= len(dates):
                self.popup_bg_canvas.itemconfigure(card["day"], text="-")
                self.popup_bg_canvas.itemconfigure(card["sun"], state="hidden")
                self.popup_bg_canvas.coords(card["icon"], card.get("center_x", 0), card.get("icon_y", 0))
                self.popup_bg_canvas.itemconfigure(card["icon"], text="•", fill=TEXT_MUTED)
                self.popup_bg_canvas.itemconfigure(card["temp"], text="--° / --°")
                continue

            forecast_style = resolve_weather_style(code_list[data_index] if data_index < len(code_list) else None, True)
            high = format_temperature(t_max[data_index] if data_index < len(t_max) else None, self.unit_symbol)
            low = format_temperature(t_min[data_index] if data_index < len(t_min) else None, self.unit_symbol)
            try:
                day_index = datetime.strptime(dates[data_index], "%Y-%m-%d").weekday()
                day_label = WEEKDAY_SHORT_FI.get(day_index, "-")
            except ValueError:
                day_label = "-"

            self.popup_bg_canvas.itemconfigure(card["day"], text=day_label)
            if forecast_style["icon"] == "🌦":
                self.popup_bg_canvas.itemconfigure(card["sun"], text="☀️", fill=ACCENT_GOLD, state="normal")
                self.popup_bg_canvas.coords(card["sun"], card.get("center_x", 0) - 8, card.get("sun_y", 0))
                self.popup_bg_canvas.coords(card["icon"], card.get("center_x", 0) + 3, card.get("icon_y", 0))
                self.popup_bg_canvas.itemconfigure(card["icon"], text="🌧", fill=forecast_style["accent"])
            elif forecast_style["icon"] == "⛅":
                self.popup_bg_canvas.itemconfigure(card["sun"], text="☀️", fill=ACCENT_GOLD, state="normal")
                self.popup_bg_canvas.coords(card["sun"], card.get("center_x", 0) - 8, card.get("sun_y", 0))
                self.popup_bg_canvas.coords(card["icon"], card.get("center_x", 0) + 3, card.get("icon_y", 0))
                self.popup_bg_canvas.itemconfigure(card["icon"], text="☁", fill="#D6DEEA")
            else:
                self.popup_bg_canvas.itemconfigure(card["sun"], state="hidden")
                self.popup_bg_canvas.coords(card["icon"], card.get("center_x", 0), card.get("icon_y", 0))
                self.popup_bg_canvas.itemconfigure(
                    card["icon"],
                    text=forecast_style["icon"],
                    fill=forecast_style["accent"],
                )
            self.popup_bg_canvas.itemconfigure(card["temp"], text=f"{high} / {low}")

        self.popup_bg_canvas.itemconfigure(self.footer_label, text="Säädata: Open-Meteo (CC BY 4.0) · Käyttöehdot")
        self._schedule_refresh()

if __name__ == "__main__":
    app = WeatherWidget()
    app.mainloop()

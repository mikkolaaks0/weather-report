import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox
from tkinter import font as tkfont
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import pystray
except Exception:  # noqa: BLE001
    pystray = None

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageTk
except Exception:  # noqa: BLE001
    Image = None
    ImageDraw = None
    ImageFilter = None
    ImageTk = None


APP_NAME = "Weather Report"
APP_SLUG = "weather-report"
APP_VERSION = "0.1.1"
APP_VERSION_DATE = "02.09.2026"
APP_VERSION_LABEL = APP_VERSION_DATE
FOOTER_TEXT = (
    f"Säädata: Open-Meteo (CC BY 4.0) · Käyttöehdot "
    f"• Versio: {APP_VERSION_LABEL}"
)
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TERMS_URL = "https://open-meteo.com/en/terms"
WINDOWS_TASKBAR_SETTINGS_URI = "ms-settings:taskbar"
REFRESH_INTERVAL_MS = 30 * 60 * 1000
FRESH_WEATHER_MAX_AGE_MINUTES = 15
UPDATE_CHECK_DELAY_MS = 10 * 1000
MAX_JSON_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CITY_QUERY_LENGTH = 120
DEFAULT_CITY = "Helsinki"
VALID_TEMPERATURE_UNITS = {"celsius", "fahrenheit"}
FORECAST_DAYS = 7
POPUP_FORECAST_DAYS = max(1, FORECAST_DAYS - 1)
RAIN_PROBABILITY_LOOKAHEAD_HOURS = 6
UPDATE_REMOTE = "origin"
UPDATE_BRANCH = "main"
PROJECT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_EXECUTABLE_PATH = Path(sys.executable).resolve()
APP_WORKING_DIR = APP_EXECUTABLE_PATH.parent if IS_FROZEN else PROJECT_DIR


def _runtime_file_signature() -> tuple[tuple[str, int, int], ...] | None:
    if IS_FROZEN:
        return None

    roots = [
        PROJECT_DIR / "main.py",
        PROJECT_DIR / "start_weather_app.bat",
        PROJECT_DIR / "start_weather_app.vbs",
        PROJECT_DIR / "assets",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(path for path in root.rglob("*") if path.is_file())

    signature: list[tuple[str, int, int]] = []
    for path in files:
        try:
            file_stat = path.stat()
        except OSError:
            continue
        signature.append(
            (
                str(path.relative_to(PROJECT_DIR)).casefold(),
                file_stat.st_mtime_ns,
                file_stat.st_size,
            )
        )
    return tuple(sorted(signature))


RUNTIME_FILE_SIGNATURE_AT_START = _runtime_file_signature()


def _resolve_settings_dir() -> Path:
    settings_root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if not settings_root:
        return APP_WORKING_DIR

    return Path(settings_root) / APP_SLUG


_settings_dir = _resolve_settings_dir()
try:
    _settings_dir.mkdir(parents=True, exist_ok=True)
except OSError:
    _settings_dir = APP_WORKING_DIR

SETTINGS_PATH = _settings_dir / "weather_settings.json"
ASSETS_DIR = RUNTIME_DIR / "assets"
APP_ICON_PATH = ASSETS_DIR / "app.ico"
APP_LOGO_PATH = ASSETS_DIR / "logo.png"
WEATHER_ICONS_DIR = ASSETS_DIR / "weather-icons"
METRIC_ICONS_DIR = ASSETS_DIR / "metric-icons"
FONTS_DIR = ASSETS_DIR / "fonts"
EXO2_FONT_FILES = (
    FONTS_DIR / "Exo2-Regular.ttf",
    FONTS_DIR / "Exo2-SemiBold.ttf",
    FONTS_DIR / "Exo2-Bold.ttf",
)
APP_FONTS_REGISTERED = False
STARTUP_SHORTCUT_NAME = f"{APP_SLUG}.lnk"
LEGACY_STARTUP_SHORTCUT_NAMES = (f"{APP_NAME}.lnk",)
DESKTOP_SHORTCUT_NAME = f"{APP_NAME}.lnk"
STARTUP_SHORTCUT_LOCK = threading.RLock()


class WeatherServiceError(RuntimeError):
    """The weather service returned a response the app cannot safely use."""


class CityNotFoundError(WeatherServiceError):
    """The requested city was not present in the geocoding response."""


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
POPUP_CONTROL_HEIGHT = 26
HERO_ICON_WIDTH = 87
HERO_ICON_HEIGHT = 84
FORECAST_ICON_WIDTH = 43
FORECAST_ICON_HEIGHT = 39
SUN_EVENT_ICON_SIZE = 15
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

APP_FONT_FAMILY = "Exo 2"
DISPLAY_FONT = APP_FONT_FAMILY
TEXT_FONT = APP_FONT_FAMILY
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


@dataclass(frozen=True)
class WeatherStyle:
    icon: str
    icon_key: str
    label: str
    accent: str


WEATHER_ICON_ALIASES = {
    "sun": "sun",
    "clear": "sun",
    "day": "sun",
    "☀": "sun",
    "☀️": "sun",
    "moon": "moon",
    "night": "moon",
    "☾": "moon",
    "☽": "moon",
    "🌙": "moon",
    "partly_cloudy": "partly-cloudy",
    "partly-cloudy": "partly-cloudy",
    "partly_cloudy_night": "partly-cloudy-night",
    "partly-cloudy-night": "partly-cloudy-night",
    "⛅": "partly-cloudy",
    "cloud": "cloud",
    "cloudy": "cloudy",
    "☁": "cloud",
    "fog": "fog",
    "mist": "fog",
    "🌫": "fog",
    "drizzle": "drizzle",
    "showers": "showers",
    "showers_night": "showers-night",
    "showers-night": "showers-night",
    "🌦": "showers",
    "rain": "rain",
    "☂": "rain",
    "🌧": "rain",
    "freezing_rain": "freezing-rain",
    "freezing-rain": "freezing-rain",
    "sleet": "sleet",
    "rain_snow": "sleet",
    "rain-snow": "sleet",
    "snow": "snow",
    "snow_showers": "snow-showers",
    "snow-showers": "snow-showers",
    "snow_showers_night": "snow-showers-night",
    "snow-showers-night": "snow-showers-night",
    "snow_grains": "snow-grains",
    "snow-grains": "snow-grains",
    "❄": "snow",
    "ice": "ice",
    "hail": "hail",
    "thunder": "thunder",
    "thunder_night": "thunder-night",
    "thunder-night": "thunder-night",
    "thunder_hail": "thunder-hail",
    "thunder-hail": "thunder-hail",
    "storm": "thunder",
    "⛈": "thunder",
    "⚡": "thunder",
    "unknown": "unknown",
    "•": "unknown",
}


def register_app_fonts() -> None:
    global APP_FONTS_REGISTERED

    if APP_FONTS_REGISTERED:
        return

    if os.name != "nt":
        APP_FONTS_REGISTERED = True
        return

    try:
        import ctypes
    except Exception:  # noqa: BLE001
        APP_FONTS_REGISTERED = True
        return

    try:
        add_font_resource = ctypes.windll.gdi32.AddFontResourceExW
        add_font_resource.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        add_font_resource.restype = ctypes.c_int
    except Exception:  # noqa: BLE001
        APP_FONTS_REGISTERED = True
        return
    private_font = 0x10

    for font_path in EXO2_FONT_FILES:
        if not font_path.exists():
            continue
        try:
            add_font_resource(str(font_path), private_font, None)
        except Exception:  # noqa: BLE001
            continue

    APP_FONTS_REGISTERED = True


def _normalize_weather_icon_key(icon_key: object) -> str:
    normalized = icon_key.strip().lower() if isinstance(icon_key, str) else ""
    return WEATHER_ICON_ALIASES.get(normalized, "unknown")


def _weather_icon_path(icon_key: str) -> Path:
    normalized = _normalize_weather_icon_key(icon_key)
    return WEATHER_ICONS_DIR / f"{normalized}.png"


def _trim_transparent_margins(image):
    if image is None or "A" not in image.getbands():
        return image

    alpha = image.getchannel("A").point(lambda value: 255 if value > 3 else 0)
    bbox = alpha.getbbox()
    if not bbox:
        return image
    return image.crop(bbox)


def _load_weather_icon_image(icon_key: str):
    if Image is None:
        return None

    candidate_paths = (
        _weather_icon_path(icon_key),
        _weather_icon_path("cloud"),
        _weather_icon_path("unknown"),
    )
    visited: set[Path] = set()
    for path in candidate_paths:
        if path in visited or not path.is_file():
            continue
        visited.add(path)
        try:
            with Image.open(path) as image:
                return image.convert("RGBA")
        except OSError:
            continue
    return None


def _resize_weather_icon_image(image, width: int, height: int):
    if Image is None or image is None:
        return None

    width = max(1, int(width))
    height = max(1, int(height))
    resampling = getattr(Image, "Resampling", Image)
    image = _trim_transparent_margins(image)
    return image.resize((width, height), resampling.LANCZOS)


def build_weather_icon_photo(icon_key: str, width: int, height: int):
    if ImageTk is None:
        return None

    image = _resize_weather_icon_image(_load_weather_icon_image(icon_key), width, height)
    if image is None:
        return None
    return ImageTk.PhotoImage(image)


def build_weather_tray_icon(icon_key: str):
    image = _resize_weather_icon_image(_load_weather_icon_image(icon_key), 64, 64)
    if image is None:
        return None
    return image


def _metric_icon_path(icon_key: str) -> Path:
    normalized = (icon_key or "").strip().lower().replace("_", "-")
    return METRIC_ICONS_DIR / f"{normalized}.png"


def _load_metric_icon_image(icon_key: str):
    if Image is None:
        return None

    path = _metric_icon_path(icon_key)
    try:
        with Image.open(path) as image:
            return image.convert("RGBA")
    except OSError:
        return None


def build_metric_icon_photo(icon_key: str, width: int, height: int):
    if ImageTk is None:
        return None

    image = _resize_weather_icon_image(_load_metric_icon_image(icon_key), width, height)
    if image is None:
        return None
    return ImageTk.PhotoImage(image)


def build_tray_symbol_icon(symbol_text: str):
    return build_weather_tray_icon(_normalize_weather_icon_key(symbol_text))


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = (color or "").strip().lstrip("#")
    if len(value) != 6:
        return (0, 0, 0)
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def build_popup_background_image(width: int, height: int, theme: dict):
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


def format_clock_fi(value: datetime) -> str:
    day_short = WEEKDAY_SHORT_FI.get(value.weekday(), "")
    return f"{day_short} {value:%d.%m.%Y %H:%M:%S}"


def _normalize_city_query(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def load_settings() -> dict:
    settings = {
        "city": DEFAULT_CITY,
        "temperature_unit": "celsius",
        "popup_theme": DEFAULT_POPUP_THEME,
    }

    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError, RecursionError):
        return settings

    if not isinstance(saved, dict):
        return settings

    city = _normalize_city_query(saved.get("city"))
    if city and len(city) <= MAX_CITY_QUERY_LENGTH:
        settings["city"] = city

    temperature_unit = _clean_text(saved.get("temperature_unit")).lower()
    if temperature_unit not in VALID_TEMPERATURE_UNITS:
        temperature_unit = "celsius"
    settings["temperature_unit"] = temperature_unit

    popup_theme = _clean_text(saved.get("popup_theme")).lower()
    if popup_theme not in POPUP_THEMES:
        popup_theme = DEFAULT_POPUP_THEME
    settings["popup_theme"] = popup_theme

    return settings


def save_settings(settings: dict) -> bool:
    temporary_path = SETTINGS_PATH.with_name(f".{SETTINGS_PATH.name}.{os.getpid()}.tmp")
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary_path, SETTINGS_PATH)
        return True
    except (OSError, TypeError, ValueError):
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _get_json(url: str, params: dict) -> dict:
    query = urlencode(params)
    request = Request(
        f"{url}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": f"{APP_SLUG}-desktop",
        },
    )
    with urlopen(request, timeout=12) as response:
        raw_payload = response.read(MAX_JSON_RESPONSE_BYTES + 1)
        charset = response.headers.get_content_charset() or "utf-8"

    if len(raw_payload) > MAX_JSON_RESPONSE_BYTES:
        raise WeatherServiceError("Sääpalvelun vastaus oli liian suuri.")

    try:
        payload = json.loads(raw_payload.decode(charset))
    except (LookupError, ValueError, RecursionError) as error:
        raise WeatherServiceError("Sääpalvelu palautti virheellisen vastauksen.") from error

    if not isinstance(payload, dict):
        raise WeatherServiceError("Sääpalvelun vastaus oli väärässä muodossa.")
    return payload


def geocode_city(city_name: str) -> dict:
    normalized_city = _normalize_city_query(city_name)
    if not normalized_city:
        raise CityNotFoundError("Paikkakunnan nimi puuttuu.")
    if len(normalized_city) > MAX_CITY_QUERY_LENGTH:
        raise WeatherServiceError(
            f"Paikkakunnan nimi saa olla enintään {MAX_CITY_QUERY_LENGTH} merkkiä."
        )

    payload = _get_json(
        GEOCODING_URL,
        {
            "name": normalized_city,
            "count": 1,
            "language": "fi",
            "format": "json",
        },
    )
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise WeatherServiceError("Paikkatiedon vastaus oli väärässä muodossa.")
    if not results:
        raise CityNotFoundError("Paikkakuntaa ei löytynyt.")

    place = results[0]
    if not isinstance(place, dict):
        raise WeatherServiceError("Paikkatiedon vastaus oli väärässä muodossa.")

    latitude, longitude = _coordinates_from_place(place)
    return {**place, "latitude": latitude, "longitude": longitude}


def get_weather(latitude: float, longitude: float, temperature_unit: str = "celsius") -> dict:
    normalized_unit = _clean_text(temperature_unit).lower()
    if normalized_unit not in VALID_TEMPERATURE_UNITS:
        normalized_unit = "celsius"

    return _get_json(
        FORECAST_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "temperature_unit": normalized_unit,
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "weather_code",
                    "wind_speed_10m",
                    "wind_direction_10m",
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


def _request_with_retry(
    operation: Callable[[], dict],
    attempts: int = 2,
    retry_delay_seconds: float = 1.0,
) -> dict:
    attempts = max(1, attempts)
    for attempt in range(attempts):
        try:
            return operation()
        except HTTPError as error:
            retryable = error.code in {408, 425, 429} or error.code >= 500
            if not retryable or attempt == attempts - 1:
                raise
            time.sleep(max(0.0, retry_delay_seconds))
        except (URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(max(0.0, retry_delay_seconds))
    raise RuntimeError("Verkkopyyntö ei palauttanut tulosta.")


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _sequence_item(values: object, index: int = 0) -> object | None:
    sequence = _as_list(values)
    return sequence[index] if 0 <= index < len(sequence) else None


def _clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _coerce_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _coordinates_from_place(place: object) -> tuple[float, float]:
    place_data = _as_dict(place)
    latitude = _coerce_number(place_data.get("latitude"))
    longitude = _coerce_number(place_data.get("longitude"))
    if (
        latitude is None
        or longitude is None
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise WeatherServiceError("Paikkatiedosta puuttuivat kelvolliset koordinaatit.")
    return latitude, longitude


def _is_daytime(value: object) -> bool:
    number = _coerce_number(value)
    return True if number is None else number != 0


def validate_weather_payload(weather: object) -> None:
    weather_data = _as_dict(weather)
    current = _as_dict(weather_data.get("current"))
    daily = _as_dict(weather_data.get("daily"))
    if not current:
        raise WeatherServiceError("Sääpalvelun vastauksesta puuttui nykytila.")
    weather_code = _coerce_number(current.get("weather_code"))
    if weather_code is None or not weather_code.is_integer():
        raise WeatherServiceError("Sääpalvelun vastauksesta puuttui kelvollinen säätilakoodi.")
    if _coerce_number(current.get("temperature_2m")) is None:
        raise WeatherServiceError("Sääpalvelun vastauksesta puuttui lämpötila.")
    if not _as_list(daily.get("time")):
        raise WeatherServiceError("Sääpalvelun vastauksesta puuttui päiväennuste.")


def resolve_weather_style(code: int | float | str | None, is_day: bool = True) -> WeatherStyle:
    numeric_code = _coerce_number(code)
    code = int(numeric_code) if numeric_code is not None and numeric_code.is_integer() else None
    if code == 0:
        return WeatherStyle(
            icon="☀" if is_day else "🌙",
            icon_key="sun" if is_day else "moon",
            label="Selkeää",
            accent=ACCENT_GOLD,
        )
    if code in {1, 2}:
        return WeatherStyle(
            icon="⛅",
            icon_key="partly-cloudy" if is_day else "partly-cloudy-night",
            label="Puolipilvistä",
            accent="#E9C37A",
        )
    if code == 3:
        return WeatherStyle(icon="☁", icon_key="cloudy", label="Pilvistä", accent="#D6DEEA")
    if code in {45, 48}:
        return WeatherStyle(icon="🌫", icon_key="fog", label="Sumua", accent="#BCC8D7")
    if code in {51, 53, 55}:
        return WeatherStyle(icon="🌦", icon_key="drizzle", label="Tihkua", accent="#8CC7FF")
    if code in {56, 57}:
        return WeatherStyle(icon="🌧", icon_key="freezing-rain", label="Jäätävää tihkua", accent="#9EDBFF")
    if code in {61, 63, 65}:
        return WeatherStyle(icon="🌧", icon_key="rain", label="Sadetta", accent=ACCENT_BLUE)
    if code in {66, 67}:
        return WeatherStyle(icon="🌧", icon_key="freezing-rain", label="Jäätävää sadetta", accent="#9EDBFF")
    if code in {71, 73, 75}:
        return WeatherStyle(icon="❄", icon_key="snow", label="Lumisadetta", accent="#BEE9FF")
    if code == 77:
        return WeatherStyle(icon="❄", icon_key="snow-grains", label="Lumijyväsiä", accent="#BEE9FF")
    if code in {80, 81, 82}:
        return WeatherStyle(
            icon="🌦",
            icon_key="showers" if is_day else "showers-night",
            label="Sadekuuroja",
            accent=ACCENT_BLUE,
        )
    if code in {85, 86}:
        return WeatherStyle(
            icon="❄",
            icon_key="snow-showers" if is_day else "snow-showers-night",
            label="Lumikuuroja",
            accent="#BEE9FF",
        )
    if code == 95:
        return WeatherStyle(
            icon="⛈",
            icon_key="thunder" if is_day else "thunder-night",
            label="Ukkosta",
            accent=ACCENT_LAVENDER,
        )
    if code in {96, 99}:
        return WeatherStyle(icon="⛈", icon_key="thunder-hail", label="Ukkosta ja rakeita", accent=ACCENT_LAVENDER)
    return WeatherStyle(icon="•", icon_key="unknown", label="Tuntematon", accent="#D5DAE3")


def format_temperature(value: object, unit_symbol: str) -> str:
    number = _coerce_number(value)
    normalized_unit = _clean_text(unit_symbol)
    if number is None:
        return f"-°{normalized_unit}"
    return f"{round(number)}°{normalized_unit}"


def format_metric(value: object, suffix: str = "", decimals: int = 0) -> str:
    number = _coerce_number(value)
    if number is None:
        return "-"
    decimals = max(0, int(decimals))
    if decimals:
        return f"{number:.{decimals}f}{suffix}"
    return f"{round(number)}{suffix}"


def format_wind_direction(value: object) -> str:
    number = _coerce_number(value)
    if number is None:
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
    index = int((number + 11.25) % 360 // 22.5)
    return directions[index]


def format_time_short(value: object) -> str:
    parsed = _parse_open_meteo_time(value)
    return parsed.strftime("%H:%M") if parsed else "-"


def _parse_open_meteo_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def max_precipitation_probability_next_hours(
    weather: object,
    hours: int = RAIN_PROBABILITY_LOOKAHEAD_HOURS,
) -> int | None:
    if hours <= 0:
        return None

    weather_data = _as_dict(weather)
    current = _as_dict(weather_data.get("current"))
    hourly = _as_dict(weather_data.get("hourly"))
    current_time = _parse_open_meteo_time(current.get("time"))
    times = _as_list(hourly.get("time"))
    probabilities = _as_list(hourly.get("precipitation_probability"))
    if current_time is None or not times or not probabilities:
        return None

    window_end = current_time + timedelta(hours=hours)
    values: list[float] = []
    for time_text, probability in zip(times, probabilities):
        hour_time = _parse_open_meteo_time(time_text)
        probability_value = _coerce_number(probability)
        if hour_time is None or probability_value is None or not 0 <= probability_value <= 100:
            continue
        try:
            in_window = current_time <= hour_time < window_end
        except TypeError:
            in_window = False
        if in_window:
            values.append(probability_value)

    if not values:
        return None
    return round(max(values))


def format_city(place: object) -> str:
    place_data = _as_dict(place)
    city = _clean_text(place_data.get("name")) or "-"
    region = _clean_text(place_data.get("admin1")) or _clean_text(place_data.get("country"))
    return f"{city}, {region}" if region else city


def _get_windows_user_shell_folder(value_name: str) -> Path | None:
    if os.name != "nt":
        return None

    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            folder_value, _value_type = winreg.QueryValueEx(key, value_name)
    except (ImportError, OSError):
        return None

    if not isinstance(folder_value, str) or not folder_value.strip():
        return None
    folder_path = Path(os.path.expandvars(folder_value.strip()))
    return folder_path if folder_path.is_absolute() else None


def get_startup_shortcut_path(name: str = STARTUP_SHORTCUT_NAME) -> Path:
    startup_dir = _get_windows_user_shell_folder("Startup")
    if startup_dir is not None:
        return startup_dir / name

    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise OSError("APPDATA-ympäristömuuttuja puuttuu.")
    startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup_dir / name


def get_desktop_shortcut_path(name: str = DESKTOP_SHORTCUT_NAME) -> Path:
    desktop_dir = _get_windows_user_shell_folder("Desktop")
    if desktop_dir is not None:
        return desktop_dir / name

    userprofile = os.environ.get("USERPROFILE")
    if not userprofile:
        raise OSError("USERPROFILE-ympäristömuuttuja puuttuu.")
    return Path(userprofile) / "Desktop" / name


def get_startup_shortcut_paths() -> list[Path]:
    primary = get_startup_shortcut_path()
    legacy_paths = [primary.with_name(name) for name in LEGACY_STARTUP_SHORTCUT_NAMES]
    return list(dict.fromkeys([primary, *legacy_paths]))


def is_startup_enabled() -> bool:
    try:
        return any(path.is_file() for path in get_startup_shortcut_paths())
    except OSError:
        return False


def _ps_escape(text: str) -> str:
    return text.replace("'", "''")


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


def _is_supported_pythonw(path: Path) -> bool:
    if not path.is_file():
        return False

    try:
        result = subprocess.run(
            [
                str(path),
                "-c",
                "import sys; raise SystemExit(sys.version_info < (3, 10))",
            ],
            check=False,
            timeout=5,
            **_hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _resolve_pythonw_executable() -> Path | None:
    current_python = Path(sys.executable).resolve()
    sibling_pythonw = current_python.with_name("pythonw.exe")
    if sibling_pythonw.is_file():
        return sibling_pythonw

    candidate = shutil.which("pythonw")
    if candidate:
        candidate_path = Path(candidate)
        if _is_supported_pythonw(candidate_path):
            return candidate_path

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        python_root = Path(local_appdata) / "Programs" / "Python"

        def version_key(path: Path) -> tuple[int, int]:
            suffix = path.name.removeprefix("Python")
            if not suffix.isdigit() or len(suffix) < 2:
                return (-1, -1)
            return (int(suffix[0]), int(suffix[1:]))

        for install_dir in sorted(python_root.glob("Python*"), key=version_key, reverse=True):
            if version_key(install_dir) < (3, 10):
                continue
            path = install_dir / "pythonw.exe"
            if _is_supported_pythonw(path):
                return path

    return None


def _resolve_wscript_executable() -> Path | None:
    if os.name != "nt":
        return None

    windows_root = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windows_root:
        system_wscript = Path(windows_root) / "System32" / "wscript.exe"
        if system_wscript.is_file():
            return system_wscript

    candidate = shutil.which("wscript.exe") or shutil.which("wscript")
    if not candidate:
        return None
    candidate_path = Path(candidate)
    return candidate_path if candidate_path.is_file() else None


def _resolve_shortcut_target() -> tuple[str, str, str, str]:
    if IS_FROZEN:
        target_path = str(APP_EXECUTABLE_PATH)
        arguments = ""
        working_dir = str(APP_EXECUTABLE_PATH.parent)
        icon_source = APP_ICON_PATH if APP_ICON_PATH.exists() else APP_EXECUTABLE_PATH
    else:
        launcher_path = (PROJECT_DIR / "start_weather_app.vbs").resolve()
        wscript_path = _resolve_wscript_executable() if launcher_path.is_file() else None
        if wscript_path is not None:
            target_path = str(wscript_path)
            arguments = subprocess.list2cmdline([str(launcher_path)])
            icon_fallback = wscript_path
        else:
            pythonw_path = _resolve_pythonw_executable()
            if pythonw_path is None:
                raise FileNotFoundError(
                    "Sopivaa Windows-käynnistintä ei löytynyt. Asenna Python 3.10 tai uudempi."
                )
            target_path = str(pythonw_path)
            arguments = subprocess.list2cmdline([str((PROJECT_DIR / "main.py").resolve())])
            icon_fallback = pythonw_path
        working_dir = str(PROJECT_DIR)
        icon_source = APP_ICON_PATH if APP_ICON_PATH.exists() else icon_fallback

    return target_path, arguments, working_dir, str(icon_source)


def create_windows_shortcut(shortcut_path: Path) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)

    if IS_FROZEN and not APP_EXECUTABLE_PATH.exists():
        raise FileNotFoundError(f"Käynnistyskohdetta ei löytynyt: {APP_EXECUTABLE_PATH.name}")

    shell_path = shutil.which("powershell") or shutil.which("pwsh")
    if not shell_path:
        raise OSError("PowerShelliä ei löytynyt pikakuvakkeen luontiin.")

    shortcut_target = str(shortcut_path)
    target_path, arguments, working_dir, icon_path = _resolve_shortcut_target()

    script = (
        "$ErrorActionPreference = 'Stop'; "
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
            [shell_path, "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            **_hidden_subprocess_kwargs(),
        )
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or "").strip()
        raise OSError(f"Pikakuvakkeen luonti epäonnistui: {details or error}") from error
    except subprocess.TimeoutExpired as error:
        raise OSError("Pikakuvakkeen luonti aikakatkaistiin.") from error

    if not shortcut_path.is_file():
        raise OSError("Pikakuvaketiedostoa ei syntynyt.")


def set_startup_enabled(enabled: bool) -> None:
    with STARTUP_SHORTCUT_LOCK:
        shortcut_path = get_startup_shortcut_path()
        shortcut_paths = get_startup_shortcut_paths()

        if not enabled:
            for candidate in shortcut_paths:
                if candidate.exists():
                    candidate.unlink()
            return

        create_windows_shortcut(shortcut_path)
        for candidate in shortcut_paths:
            if candidate != shortcut_path and candidate.exists():
                candidate.unlink()


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
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
        text=True,
        timeout=timeout,
        **_hidden_subprocess_kwargs(),
    )


def _git_output(args: list[str], timeout: int = 30) -> str:
    try:
        result = _run_git_command(args, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Git-komento aikakatkaistiin: git {' '.join(args)}") from error
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(details or f"git {' '.join(args)} epäonnistui.")
    return result.stdout.strip()


def check_github_update_status() -> dict:
    if IS_FROZEN:
        return {"state": "unsupported", "message": "Automaattinen Git-päivitys toimii lähdekoodiasennuksessa."}

    if not (PROJECT_DIR / ".git").exists():
        return {"state": "unsupported", "message": "Sovelluskansio ei ole Git-repositorio."}

    try:
        inside_worktree = _run_git_command(["rev-parse", "--is-inside-work-tree"])
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git-repositorion tarkistus aikakatkaistiin.") from error
    if inside_worktree.returncode != 0:
        details = (inside_worktree.stderr or inside_worktree.stdout or "").strip()
        raise RuntimeError(details or "Git-repositorion tarkistus epäonnistui.")
    if inside_worktree.stdout.strip().lower() != "true":
        return {"state": "unsupported", "message": "Sovelluskansio ei ole Git-repositorio."}

    current_branch = _git_output(["branch", "--show-current"])
    if current_branch != UPDATE_BRANCH:
        branch_label = current_branch or "detached HEAD"
        return {
            "state": "unsupported",
            "message": (
                "Automaattinen Git-päivitys on sallittu vain "
                f"{UPDATE_BRANCH}-branchissa. Nykyinen branch: {branch_label}."
            ),
        }

    status = _git_output(["status", "--porcelain"])
    if status:
        return {"state": "dirty", "message": "Paikallisia muutoksia on auki, päivitystä ei tehdä automaattisesti."}

    # An already-downloaded update can be activated even without a network connection.
    if _runtime_file_signature() != RUNTIME_FILE_SIGNATURE_AT_START:
        return {
            "state": "restart_available",
            "message": (
                "Paikallinen sovellusversio on jo päivittynyt. "
                "Käynnistä sovellus uudelleen, jotta muutos tulee käyttöön."
            ),
        }

    _git_output(["fetch", UPDATE_REMOTE, UPDATE_BRANCH], timeout=60)
    local_sha = _git_output(["rev-parse", "HEAD"])
    remote_ref = f"{UPDATE_REMOTE}/{UPDATE_BRANCH}"
    remote_sha = _git_output(["rev-parse", remote_ref])
    if local_sha == remote_sha:
        return {"state": "current", "message": f"Sovellus on ajan tasalla. Versio: {APP_VERSION_LABEL}."}

    try:
        ancestor = _run_git_command(["merge-base", "--is-ancestor", "HEAD", remote_ref])
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git-versioiden vertailu aikakatkaistiin.") from error
    if ancestor.returncode == 0:
        return {"state": "available", "local": local_sha, "remote": remote_sha}
    if ancestor.returncode == 1:
        return {
            "state": "diverged",
            "message": "Paikallinen ja GitHubin versio ovat eronneet; automaattinen päivitys ohitetaan.",
        }

    details = (ancestor.stderr or ancestor.stdout or "").strip()
    raise RuntimeError(details or "Git-versioiden vertailu epäonnistui.")


def apply_github_update() -> None:
    current_branch = _git_output(["branch", "--show-current"])
    if current_branch != UPDATE_BRANCH:
        branch_label = current_branch or "detached HEAD"
        raise RuntimeError(
            "Automaattinen Git-päivitys voidaan tehdä vain "
            f"{UPDATE_BRANCH}-branchissa. Nykyinen branch: {branch_label}."
        )

    if _git_output(["status", "--porcelain"]):
        raise RuntimeError("Paikallisia muutoksia on auki, päivitystä ei tehdä automaattisesti.")

    try:
        result = _run_git_command(["pull", "--ff-only", UPDATE_REMOTE, UPDATE_BRANCH], timeout=120)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("GitHub-päivitys aikakatkaistiin.") from error
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(details or "GitHub-päivitys epäonnistui.")


def restart_application() -> subprocess.Popen:
    if IS_FROZEN:
        args = [str(APP_EXECUTABLE_PATH)]
    else:
        # Reuse the working environment, including virtualenv-installed dependencies.
        executable = Path(sys.executable)
        pythonw = executable.with_name("pythonw.exe")
        if os.name == "nt" and pythonw.is_file():
            executable = pythonw
        args = [str(executable), str(PROJECT_DIR / "main.py")]

    return subprocess.Popen(  # noqa: S603
        args,
        cwd=str(APP_WORKING_DIR),
        close_fds=True,
        **_hidden_subprocess_kwargs(),
    )


class WeatherWidget(tk.Tk):
    def __init__(self) -> None:
        register_app_fonts()
        super().__init__()

        self.settings = load_settings()
        self.unit_symbol = "C" if self.settings.get("temperature_unit") == "celsius" else "F"
        self.city_var = tk.StringVar(value=self.settings.get("city", DEFAULT_CITY))
        self.detail_city_var = tk.StringVar(value=self.city_var.get())
        self.status_var = tk.StringVar(value="Päivitetään säätä...")
        self.clock_var = tk.StringVar(value="--")
        self.startup_change_in_progress = False
        self.desktop_shortcut_in_progress = False
        self._settings_save_pending = False
        self.popup_theme_id = self._resolve_popup_theme_id(self.settings.get("popup_theme"))
        self.fetch_in_progress = False
        self.pending_city_search: str | None = None
        self.update_check_in_progress = False
        self._is_destroying = False
        self._ui_thread_id = threading.get_ident()
        self._ui_callbacks: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self.refresh_job: str | None = None
        self.clock_job: str | None = None
        self.bootstrap_job: str | None = None
        self.update_job: str | None = None
        self.restart_job: str | None = None
        self.ui_poll_job: str | None = None
        self.popup: tk.Toplevel | None = None
        self.forecast_cards: list[dict] = []
        self.latest_place: dict | None = None
        self.latest_weather: dict | None = None
        self.last_weather_update: datetime | None = None
        self.tray_icon = None
        self.tray_symbol = "cloud"
        self.popup_bg_photo = None
        self.weather_icon_photo_cache: dict[tuple[str, int, int], tk.PhotoImage] = {}
        self.rain_mm_umbrella_icon_photo = build_metric_icon_photo("umbrella", 14, 14)
        self.rain_prob_drop_icon_photo = build_metric_icon_photo("drop", 12, 14)
        self.humidity_fog_icon_photo = build_metric_icon_photo("fog", 16, 14)
        self.wind_swirl_icon_photo = build_metric_icon_photo("wind", 18, 14)
        self.sunrise_sun_icon_photo = self._weather_icon_photo("sun", SUN_EVENT_ICON_SIZE, SUN_EVENT_ICON_SIZE)
        self.sunset_moon_icon_photo = self._weather_icon_photo("moon", SUN_EVENT_ICON_SIZE, SUN_EVENT_ICON_SIZE)
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
        self.ui_poll_job = self.after(50, self._drain_ui_callbacks)
        self.clock_job = self.after(300, self._tick_clock)
        self.bootstrap_job = self.after(700, self.refresh_weather)
        if not IS_FROZEN:
            self.update_job = self.after(UPDATE_CHECK_DELAY_MS, self.check_for_app_update)
        self.after(1500, self._refresh_startup_shortcut_if_enabled)

    def _persist_settings(self) -> None:
        was_pending = self._settings_save_pending
        self._settings_save_pending = not save_settings(self.settings)
        if self._settings_save_pending and not was_pending:
            messagebox.showwarning(
                APP_NAME,
                "Asetusten tallennus epäonnistui. Muutokset ovat käytössä tässä istunnossa, "
                "mutta voivat kadota uudelleenkäynnistyksessä. Tallennusta yritetään uudelleen "
                "seuraavan onnistuneen sääpäivityksen yhteydessä.\n\n"
                f"Asetustiedosto: {SETTINGS_PATH}",
            )

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

    def _weather_icon_photo(self, icon_key: str, width: int, height: int):
        normalized = _normalize_weather_icon_key(icon_key)
        cache_key = (normalized, int(width), int(height))
        cached = self.weather_icon_photo_cache.get(cache_key)
        if cached is not None:
            return cached

        photo = build_weather_icon_photo(normalized, width, height)
        if photo is not None:
            self.weather_icon_photo_cache[cache_key] = photo
        return photo

    def _configure_weather_label(
        self,
        label: tk.Label,
        icon_key: str,
        width: int,
        height: int,
        fallback_symbol: str,
        accent: str,
    ) -> None:
        photo = self._weather_icon_photo(icon_key, width, height)
        if photo is not None:
            label.config(image=photo, text="", width=width, height=height)
            return

        label.config(image="", text=fallback_symbol, width=0, height=0, fg=accent)

    def _configure_canvas_weather_icon(
        self,
        item_id: int,
        icon_key: str,
        width: int,
        height: int,
    ) -> None:
        photo = self._weather_icon_photo(icon_key, width, height)
        if photo is not None:
            self.popup_bg_canvas.itemconfigure(item_id, image=photo, state="normal")
            return
        self.popup_bg_canvas.itemconfigure(item_id, state="hidden")

    def _init_tray_icon(self) -> None:
        if pystray is None or Image is None:
            self.status_var.set("Tray-tuki puuttuu (pystray/pillow).")
            self.deiconify()
            return

        menu_items = [
            pystray.MenuItem(
                "Näytä/piilota viikkonäkymä",
                lambda _icon, _item: self._call_on_ui_thread(self.toggle_popup),
                default=True,
            ),
            pystray.MenuItem(
                "Päivitä sää",
                lambda _icon, _item: self._call_on_ui_thread(self.refresh_weather),
            ),
            pystray.MenuItem(
                "Käynnistä tietokoneen käynnistyessä",
                lambda _icon, _item: self._call_on_ui_thread(self._toggle_startup_from_tray),
                checked=lambda _item: is_startup_enabled(),
            ),
            pystray.MenuItem(
                "Luo pikakuvake työpöydälle",
                lambda _icon, _item: self._call_on_ui_thread(self._create_desktop_shortcut_from_tray),
            ),
            pystray.MenuItem(
                "Näytä kuvakerivissä",
                lambda _icon, _item: self._call_on_ui_thread(self._open_taskbar_icon_settings),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Lopeta",
                lambda _icon, _item: self._call_on_ui_thread(self._quit_from_tray),
            ),
        ]
        if not IS_FROZEN:
            menu_items.insert(
                2,
                pystray.MenuItem(
                    "Tarkista sovelluspäivitys",
                    lambda _icon, _item: self._call_on_ui_thread(
                        lambda: self.check_for_app_update(manual=True)
                    ),
                ),
            )
        menu = pystray.Menu(*menu_items)

        tray_image = build_tray_symbol_icon(self.tray_symbol)
        if tray_image is None:
            self.status_var.set("Tray-kuvaketta ei voitu luoda.")
            self.deiconify()
            return

        try:
            self.tray_icon = pystray.Icon(APP_SLUG, tray_image, APP_NAME, menu)
            self.tray_icon.run_detached()
        except Exception as error:  # noqa: BLE001
            self.tray_icon = None
            self.status_var.set(f"Tray-kuvakkeen käynnistys epäonnistui: {error}")
            self.deiconify()

    def _stop_tray_icon(self) -> None:
        if self.tray_icon is None:
            return

        try:
            self.tray_icon.stop()
        except Exception:  # noqa: BLE001
            pass
        self.tray_icon = None

    def _toggle_startup_from_tray(self) -> None:
        if self.startup_change_in_progress:
            return
        desired_state = not is_startup_enabled()
        self.startup_change_in_progress = True
        self.status_var.set("Päivitetään käynnistysasetusta...")

        def worker() -> None:
            error_text = None
            try:
                set_startup_enabled(desired_state)
            except Exception as error:  # noqa: BLE001
                error_text = str(error)
            self._call_on_ui_thread(lambda: self._finish_startup_change(error_text))

        self._start_background_worker(worker)

    def _finish_startup_change(self, error_text: str | None) -> None:
        self.startup_change_in_progress = False
        if self.tray_icon:
            self.tray_icon.update_menu()
        if error_text:
            message = f"Käynnistysasetuksen päivitys epäonnistui: {error_text}"
            self.status_var.set(message)
            messagebox.showerror(APP_NAME, message)
        elif is_startup_enabled():
            self.status_var.set("Automaattinen käynnistys päällä. Toteutus on kevyt Startup-pikakuvake.")
        else:
            self.status_var.set("Automaattinen käynnistys poistettu käytöstä.")

    def _create_desktop_shortcut_from_tray(self) -> None:
        if self.desktop_shortcut_in_progress:
            return
        self.desktop_shortcut_in_progress = True
        self.status_var.set("Luodaan työpöydän pikakuvaketta...")

        def worker() -> None:
            shortcut_path = None
            error_text = None
            try:
                shortcut_path = create_desktop_shortcut()
            except Exception as error:  # noqa: BLE001
                error_text = str(error)
            self._call_on_ui_thread(lambda: self._finish_desktop_shortcut(shortcut_path, error_text))

        self._start_background_worker(worker)

    def _finish_desktop_shortcut(self, shortcut_path: Path | None, error_text: str | None) -> None:
        self.desktop_shortcut_in_progress = False
        if shortcut_path is None:
            message = f"Työpöydän pikakuvakkeen luonti epäonnistui: {error_text or 'Kohdetta ei saatu.'}"
            self.status_var.set(message)
            messagebox.showerror(APP_NAME, message)
            return

        self.status_var.set(f"Pikakuvake luotu: {shortcut_path.name}")
        messagebox.showinfo(APP_NAME, f"Pikakuvake luotiin työpöydälle: {shortcut_path.name}")

    def _open_taskbar_icon_settings(self) -> None:
        if os.name != "nt":
            self.status_var.set("Kuvakerivin näkyvyys säädetään käyttöjärjestelmän asetuksista.")
            return

        try:
            os.startfile(WINDOWS_TASKBAR_SETTINGS_URI)  # type: ignore[attr-defined] # noqa: S606
        except OSError:
            self.status_var.set("Tehtäväpalkin asetusten avaaminen epäonnistui.")
            return

        self.status_var.set("Asetuksissa: Muut ilmaisinalueen kuvakkeet -> Weather Report päälle.")

    def _refresh_startup_shortcut_if_enabled(self) -> None:
        if not is_startup_enabled():
            return

        def worker() -> None:
            try:
                with STARTUP_SHORTCUT_LOCK:
                    if is_startup_enabled():
                        set_startup_enabled(True)
            except Exception as error:  # noqa: BLE001
                self._call_on_ui_thread(
                    lambda error=error: self.status_var.set(
                        f"Startup-pikakuvakkeen korjaus epäonnistui: {error}"
                    )
                )

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
            self._call_on_ui_thread(
                lambda status=status, manual=manual: self._handle_update_check_result(status, manual)
            )

        self._start_background_worker(worker)

    def _handle_update_check_result(self, status: dict, manual: bool) -> None:
        state = status.get("state")

        if state == "available":
            should_update = messagebox.askyesno(
                APP_NAME,
                f"GitHubissa on uudempi versio kuin {APP_VERSION_LABEL}. "
                "Päivitetäänkö sovellus nyt ja käynnistetäänkö se uudelleen?",
            )
            if should_update:
                self._apply_app_update()
            else:
                self.status_var.set("Sovelluspäivitys ohitettiin.")
                self.update_check_in_progress = False
            return

        if state == "restart_available":
            should_restart = messagebox.askyesno(
                APP_NAME,
                "Sovelluksen tiedostot ovat jo päivittyneet levylle. "
                "Käynnistetäänkö sovellus uudelleen nyt?",
            )
            if should_restart:
                self._finish_app_update(None)
            else:
                self.status_var.set("Sovelluksen uudelleenkäynnistys ohitettiin.")
                self.update_check_in_progress = False
            return

        message = status.get("message", "Sovelluspäivitystä ei voitu tarkistaa.")
        if manual or state not in {"current"}:
            self.status_var.set(message)
        if manual:
            if state == "error":
                messagebox.showerror(APP_NAME, message)
            else:
                messagebox.showinfo(APP_NAME, message)
        self.update_check_in_progress = False

    def _apply_app_update(self) -> None:
        self.update_check_in_progress = True
        self.status_var.set("Päivitetään sovellusta GitHubista...")

        def worker() -> None:
            error_text = None
            try:
                apply_github_update()
            except Exception as error:  # noqa: BLE001
                error_text = str(error)
            self._call_on_ui_thread(lambda error_text=error_text: self._finish_app_update(error_text))

        self._start_background_worker(worker)

    def _finish_app_update(self, error_text: str | None) -> None:
        if error_text:
            self.status_var.set(f"Sovelluspäivitys epäonnistui: {error_text}")
            messagebox.showerror(APP_NAME, f"Sovelluspäivitys epäonnistui: {error_text}")
            self.update_check_in_progress = False
            return

        self.status_var.set("Sovellus päivitetty. Käynnistetään uudelleen...")
        try:
            process = restart_application()
        except Exception as error:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Päivitys onnistui, mutta uudelleenkäynnistys epäonnistui: {error}")
            self.update_check_in_progress = False
            return
        self.restart_job = self.after(1500, lambda: self._check_restart_process(process))

    def _check_restart_process(self, process: subprocess.Popen) -> None:
        self.restart_job = None
        if process.poll() is not None:
            message = "Uusi sovellus sulkeutui käynnistyksessä. Nykyinen sovellus jätettiin käyttöön."
            self.status_var.set(message)
            messagebox.showerror(APP_NAME, message)
            self.update_check_in_progress = False
            return
        self.destroy()

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

    def _call_on_ui_thread(self, callback: Callable[[], None]) -> None:
        if self._is_destroying:
            return
        if threading.get_ident() == self._ui_thread_id:
            callback()
            return
        self._ui_callbacks.put(callback)

    def _drain_ui_callbacks(self) -> None:
        self.ui_poll_job = None
        if self._is_destroying:
            return

        for _ in range(100):
            try:
                callback = self._ui_callbacks.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:  # noqa: BLE001
                self.report_callback_exception(*sys.exc_info())
            if self._is_destroying:
                break

        if not self._is_destroying:
            self.ui_poll_job = self.after(50, self._drain_ui_callbacks)

    def destroy(self) -> None:
        if self._is_destroying:
            return
        self._is_destroying = True
        if self._settings_save_pending:
            save_settings(self.settings)

        for job_name in ("clock_job", "refresh_job", "bootstrap_job", "update_job", "restart_job", "ui_poll_job"):
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
            text="",
            fg=ACCENT_GOLD,
            bg=SURFACE_BG,
            width=42,
            height=42,
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
        self._configure_weather_label(self.widget_icon_label, "moon", 42, 42, "🌙", ACCENT_GOLD)

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
        self.hero_icon_label = self.popup_bg_canvas.create_image(
            0,
            0,
            anchor="w",
        )
        self.hero_temp_label = self.popup_bg_canvas.create_text(
            0,
            0,
            text="--°C",
            anchor="nw",
            font=(DISPLAY_FONT, 54, "bold"),
            fill="#FFFFFF",
        )
        if self.rain_mm_umbrella_icon_photo is not None:
            self.today_rain_mm_icon_label = self.popup_bg_canvas.create_image(
                0,
                0,
                image=self.rain_mm_umbrella_icon_photo,
                anchor="ne",
            )
        else:
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
        if self.sunrise_sun_icon_photo is not None:
            self.today_sun_icon_label = self.popup_bg_canvas.create_image(
                0,
                0,
                image=self.sunrise_sun_icon_photo,
                anchor="ne",
            )
        else:
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
        if self.sunset_moon_icon_photo is not None:
            self.today_moon_icon_label = self.popup_bg_canvas.create_image(
                0,
                0,
                image=self.sunset_moon_icon_photo,
                anchor="ne",
            )
        else:
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
            text=FOOTER_TEXT,
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
            icon_id = self.popup_bg_canvas.create_image(
                0,
                0,
                anchor="n",
            )
            temp_id = self.popup_bg_canvas.create_text(
                0,
                0,
                text="--° / --°",
                anchor="n",
                font=(TEXT_FONT, 10),
                fill="#F3F7FF",
            )
            self.forecast_cards.append({"day": day_id, "icon": icon_id, "temp": temp_id})

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
        self.location_entry.pack(side="left", fill="both", expand=True, ipady=2)
        self.location_entry.bind("<Return>", lambda _: self._search_from_popup())

        self.search_button = self._create_icon_button(self.popup_bg_canvas, "Hae", self._search_from_popup, width=4)
        self.refresh_button = self._create_icon_button(self.popup_bg_canvas, "⟳", self.refresh_weather)
        self.close_button = self._create_icon_button(self.popup_bg_canvas, "✕", self._hide_popup)
        self._configure_canvas_weather_icon(
            self.hero_icon_label,
            "cloud",
            HERO_ICON_WIDTH,
            HERO_ICON_HEIGHT,
        )
        for card in self.forecast_cards:
            self._configure_canvas_weather_icon(
                card["icon"],
                "unknown",
                FORECAST_ICON_WIDTH,
                FORECAST_ICON_HEIGHT,
            )

        self.location_entry_window = self.popup_bg_canvas.create_window(
            0,
            0,
            window=self.location_entry_shell,
            anchor="ne",
            height=POPUP_CONTROL_HEIGHT,
        )
        self.search_button_window = self.popup_bg_canvas.create_window(
            0,
            0,
            window=self.search_button,
            anchor="ne",
            height=POPUP_CONTROL_HEIGHT,
        )
        self.refresh_button_window = self.popup_bg_canvas.create_window(
            0,
            0,
            window=self.refresh_button,
            anchor="ne",
            height=POPUP_CONTROL_HEIGHT,
        )
        self.close_button_window = self.popup_bg_canvas.create_window(
            0,
            0,
            window=self.close_button,
            anchor="ne",
            height=POPUP_CONTROL_HEIGHT,
        )
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

        self.popup_bg_canvas.coords(self.clock_label, pad + left_nudge, 12)
        self.popup_bg_canvas.itemconfigure(self.clock_label, text=self.clock_var.get())
        self.popup_bg_canvas.coords(self.hero_updated_label, pad + left_nudge, 32)

        self.popup.update_idletasks()
        control_y = 12
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

        self.popup_bg_canvas.coords(self.hero_city_label, pad + left_nudge, 57)
        self.popup_bg_canvas.coords(self.hero_icon_label, pad + 8 + left_nudge, 157)
        self.popup_bg_canvas.coords(self.hero_temp_label, pad + 116 + left_nudge, 95)

        right_text = width - pad - 14
        right_stack_top = 58
        self._layout_today_weather_stack(right_text, right_stack_top)

        forecast_top = height - 116
        forecast_side_inset = 12
        forecast_left = pad + forecast_side_inset
        usable_width = max(1, width - (forecast_left * 2))
        col_width = usable_width / max(1, POPUP_FORECAST_DAYS)
        for index, card in enumerate(self.forecast_cards):
            center_x = int(forecast_left + (index + 0.5) * col_width)
            card["center_x"] = center_x
            card["icon_y"] = forecast_top + 22
            self.popup_bg_canvas.coords(card["day"], center_x, forecast_top)
            self.popup_bg_canvas.coords(card["icon"], center_x, card["icon_y"])
            self.popup_bg_canvas.coords(card["temp"], center_x, forecast_top + 68)

        self.popup_bg_canvas.coords(self.footer_label, width - pad, height - 7)

    def _layout_today_weather_stack(self, right_text: int, right_stack_top: int) -> None:
        self.popup_bg_canvas.coords(self.today_condition_label, right_text - 4, right_stack_top + 2)
        self.popup_bg_canvas.coords(self.today_hilo_label, right_text, right_stack_top + 38)
        sun_row_y = right_stack_top + 67
        icon_time_gap = 4
        sun_event_icon_y_offset = 5
        sun_event_icon_left_nudge = 3
        sunrise_icon_extra_left_nudge = 1
        group_gap = 16
        self.popup_bg_canvas.coords(self.today_sunset_time_label, right_text, sun_row_y)
        self.popup.update_idletasks()
        sunset_bbox = self.popup_bg_canvas.bbox(self.today_sunset_time_label)
        sunset_left = sunset_bbox[0] if sunset_bbox else (right_text - 36)

        self.popup_bg_canvas.coords(
            self.today_moon_icon_label,
            sunset_left - icon_time_gap - sun_event_icon_left_nudge,
            sun_row_y + sun_event_icon_y_offset,
        )
        moon_bbox = self.popup_bg_canvas.bbox(self.today_moon_icon_label)
        moon_left = moon_bbox[0] if moon_bbox else (sunset_left - 14)

        self.popup_bg_canvas.coords(self.today_sunrise_time_label, moon_left - group_gap, sun_row_y)
        sunrise_bbox = self.popup_bg_canvas.bbox(self.today_sunrise_time_label)
        sunrise_left = sunrise_bbox[0] if sunrise_bbox else (moon_left - 42)

        self.popup_bg_canvas.coords(
            self.today_sun_icon_label,
            sunrise_left - icon_time_gap - sun_event_icon_left_nudge - sunrise_icon_extra_left_nudge,
            sun_row_y + sun_event_icon_y_offset,
        )
        self._layout_today_stats(right_text, right_stack_top + 91)

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
        self.popup_bg_canvas.coords(self.today_rain_mm_icon_label, rain_mm_left - icon_value_gap, top_y + 2)

        # Second row: wind.
        wind_y = top_y + line_height + 2
        self.popup_bg_canvas.coords(self.today_wind_value_label, right_x, wind_y)
        wind_bbox = self.popup_bg_canvas.bbox(self.today_wind_value_label)
        wind_left = wind_bbox[0] if wind_bbox else (right_x - 72)
        self.popup_bg_canvas.coords(
            self.today_wind_icon_label,
            wind_left - icon_value_gap,
            wind_y + wind_icon_y_offset,
        )

    def _draw_popup_gradient(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return

        theme = self._current_popup_theme()
        cache_key = (width, height, self.popup_theme_id)
        if self.popup_bg_size == cache_key:
            return

        self.popup_bg_size = cache_key
        self.popup_bg_canvas.delete("grad")
        self.popup_bg_photo = build_popup_background_image(width, height, theme=theme)
        if self.popup_bg_photo is not None:
            self.popup_bg_canvas.create_image(0, 0, anchor="nw", image=self.popup_bg_photo, tags="grad")
            self.popup_bg_canvas.tag_lower("grad")

    def _apply_popup_round_corners(self, radius: int = POPUP_CORNER_RADIUS) -> None:
        if not self.popup or os.name != "nt":
            return

        try:
            import ctypes
            from ctypes import wintypes

            width = max(1, self.popup.winfo_width())
            height = max(1, self.popup.winfo_height())
            hwnd = self.popup.winfo_id()

            create_region = ctypes.windll.gdi32.CreateRoundRectRgn
            create_region.argtypes = [ctypes.c_int] * 6
            create_region.restype = wintypes.HANDLE
            set_window_region = ctypes.windll.user32.SetWindowRgn
            set_window_region.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
            set_window_region.restype = ctypes.c_int
            delete_object = ctypes.windll.gdi32.DeleteObject
            delete_object.argtypes = [wintypes.HGDIOBJ]
            delete_object.restype = wintypes.BOOL

            region = create_region(0, 0, width + 1, height + 1, radius, radius)
            if region and not set_window_region(hwnd, region, True):
                delete_object(region)
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
            pady=0,
            highlightthickness=0,
        )

    def _position_widget(self) -> None:
        self.update_idletasks()
        width = 322
        height = 84
        x_pos = max(0, self.winfo_screenwidth() - width - 20)
        y_pos = max(0, self.winfo_screenheight() - height - 70)
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

        available_width = max(1, right - left - 10)
        popup_width = min(popup_width, available_width)

        available_height = max(1, bottom - top - 10)
        popup_height = min(popup_height, available_height)

        x_pos = max(left + 5, right - popup_width - 5)
        y_pos = max(top + 3, bottom - popup_height - 3)

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

        age = datetime.now() - self.last_weather_update
        if age < timedelta(0) or age > timedelta(minutes=FRESH_WEATHER_MAX_AGE_MINUTES):
            self.refresh_weather()

    def _search_from_popup(self) -> None:
        self.refresh_weather(self.detail_city_var.get())

    def _open_open_meteo_terms(self) -> None:
        try:
            opened = webbrowser.open_new_tab(OPEN_METEO_TERMS_URL)
        except Exception:
            self.status_var.set("Open-Meteo-linkin avaaminen epäonnistui.")
            return
        if not opened:
            self.status_var.set("Open-Meteo-linkin avaaminen epäonnistui.")

    def _resolve_popup_theme_id(self, theme_id: str | None) -> str:
        candidate = _clean_text(theme_id).lower()
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
        self.popup_bg_size = None
        self._update_theme_dot_color()

        if self.popup:
            width = max(1, self.popup.winfo_width())
            height = max(1, self.popup.winfo_height())
            self._draw_popup_gradient(width, height)

        self.status_var.set(f"Väriteema: {self._current_popup_theme().get('name', resolved)}")
        self._persist_settings()

    def _cycle_popup_theme(self, _event: tk.Event | None = None) -> None:
        self._set_popup_theme(self._next_popup_theme_id())

    def refresh_weather(self, city_override: str | None = None) -> None:
        city = _normalize_city_query(
            city_override if city_override is not None else self.city_var.get()
        )
        if not city:
            messagebox.showinfo(APP_NAME, "Kirjoita paikkakunnan nimi.")
            return
        if len(city) > MAX_CITY_QUERY_LENGTH:
            messagebox.showinfo(
                APP_NAME,
                f"Paikkakunnan nimi saa olla enintään {MAX_CITY_QUERY_LENGTH} merkkiä.",
            )
            return

        if self.fetch_in_progress:
            if city_override is not None:
                self.pending_city_search = city
                self.status_var.set(f"Kaupunkihaku odottaa: {city}")
            return

        self.fetch_in_progress = True
        if city_override is not None:
            self.pending_city_search = None
        self.status_var.set(f"Haetaan säätä: {city}")
        temperature_unit = self.settings.get("temperature_unit", "celsius")
        place_hint = self.latest_place if city_override is None else None
        self._start_background_worker(
            lambda: self._fetch_worker(city, temperature_unit, place_hint)
        )

    def _fetch_worker(self, city: str, temperature_unit: str, place_hint: dict | None) -> None:
        try:
            place = place_hint or _request_with_retry(lambda: geocode_city(city))
            latitude, longitude = _coordinates_from_place(place)

            weather = _request_with_retry(
                lambda: get_weather(
                    latitude,
                    longitude,
                    temperature_unit,
                )
            )
            validate_weather_payload(weather)

            self._call_on_ui_thread(
                lambda place=place, weather=weather, city=city: self._handle_weather_result(
                    place,
                    weather,
                    city,
                )
            )
        except CityNotFoundError as error:
            message = str(error)
            self._call_on_ui_thread(lambda message=message: self._show_error(message, notify_user=True))
        except (URLError, TimeoutError):
            self._call_on_ui_thread(lambda: self._show_error("Verkkovirhe. Tarkista internet-yhteys."))
        except WeatherServiceError as error:
            message = str(error)
            self._call_on_ui_thread(lambda message=message: self._show_error(message))
        except Exception as error:  # noqa: BLE001
            message = f"Säätietojen haku epäonnistui: {error}"
            self._call_on_ui_thread(lambda message=message: self._show_error(message))

    def _handle_weather_result(self, place: dict, weather: dict, requested_city: str) -> None:
        try:
            self._apply_weather(place, weather, requested_city)
        except WeatherServiceError as error:
            self._show_error(str(error))
        except Exception:  # noqa: BLE001
            self._show_error("Säädatan käsittely epäonnistui.")

    def _show_error(self, text: str, notify_user: bool = False) -> None:
        self.fetch_in_progress = False
        self.status_var.set(f"Päivitys epäonnistui: {text} Yritetään uudelleen 30 minuutin päästä.")
        # Keep the last successful weather symbol in tray after transient fetch errors.
        # Show the bullet only when we do not have any weather data yet.
        if self.latest_weather:
            current = _as_dict(self.latest_weather.get("current"))
            style = resolve_weather_style(current.get("weather_code"), _is_daytime(current.get("is_day")))
            city_text = format_city(self.latest_place) if isinstance(self.latest_place, dict) else self.city_var.get()
            current_temp = format_temperature(current.get("temperature_2m"), self.unit_symbol)
            self._update_tray_symbol(style.icon_key, f"{city_text}: {current_temp} (päivitys epäonnistui)")
        else:
            self._update_tray_symbol("unknown", f"{APP_NAME}: päivitys epäonnistui")
        if notify_user or not self.latest_weather:
            messagebox.showerror(APP_NAME, text)
        self._schedule_refresh()
        self._run_pending_city_search()

    def _run_pending_city_search(self) -> None:
        city = self.pending_city_search
        if not city or self._is_destroying:
            return
        self.pending_city_search = None
        self.refresh_weather(city)

    def _schedule_refresh(self) -> None:
        if self.refresh_job is not None:
            try:
                self.after_cancel(self.refresh_job)
            except tk.TclError:
                pass
        self.refresh_job = self.after(REFRESH_INTERVAL_MS, self._run_scheduled_refresh)

    def _run_scheduled_refresh(self) -> None:
        self.refresh_job = None
        self.refresh_weather()

    def _apply_current_weather_summary(
        self,
        style: WeatherStyle,
        current_temp: str,
        city_text: str,
        updated_text: str,
    ) -> None:
        self._configure_weather_label(
            self.widget_icon_label,
            style.icon_key,
            42,
            42,
            style.icon,
            style.accent,
        )
        self.widget_temp_label.config(text=current_temp)
        self.widget_city_label.config(text=city_text)
        self.widget_condition_label.config(text=style.label)

        self._configure_canvas_weather_icon(
            self.hero_icon_label,
            style.icon_key,
            HERO_ICON_WIDTH,
            HERO_ICON_HEIGHT,
        )
        self.popup_bg_canvas.itemconfigure(self.hero_temp_label, text=current_temp)
        self.popup_bg_canvas.itemconfigure(self.hero_city_label, text=city_text)
        self.popup_bg_canvas.itemconfigure(self.hero_updated_label, text=updated_text)

    def _apply_today_detail_metrics(
        self,
        condition_label: str,
        high_low_text: str,
        rain_mm: str,
        rain_probability: str,
        humidity: str,
        wind: str,
        sunrise: str,
        sunset: str,
    ) -> None:
        self.popup_bg_canvas.itemconfigure(self.today_rain_mm_value_label, text=rain_mm)
        self.popup_bg_canvas.itemconfigure(self.today_rain_prob_value_label, text=rain_probability)
        self.popup_bg_canvas.itemconfigure(self.today_humidity_value_label, text=humidity)
        self.popup_bg_canvas.itemconfigure(self.today_wind_value_label, text=wind)
        self.popup_bg_canvas.itemconfigure(self.today_condition_label, text=condition_label)
        self.popup_bg_canvas.itemconfigure(self.today_hilo_label, text=high_low_text)
        self.popup_bg_canvas.itemconfigure(self.today_sunrise_time_label, text=sunrise)
        self.popup_bg_canvas.itemconfigure(self.today_sunset_time_label, text=sunset)

        condition_coords = self.popup_bg_canvas.coords(self.today_condition_label)
        if condition_coords:
            right_text = int(condition_coords[0]) + 4
            right_stack_top = int(condition_coords[1]) - 2
            self._layout_today_weather_stack(right_text, right_stack_top)

    def _apply_forecast_cards(self, daily: dict) -> None:
        daily_data = _as_dict(daily)
        dates = _as_list(daily_data.get("time"))
        code_list = _as_list(daily_data.get("weather_code"))
        t_min = _as_list(daily_data.get("temperature_2m_min"))
        t_max = _as_list(daily_data.get("temperature_2m_max"))

        for index, card in enumerate(self.forecast_cards):
            data_index = index + 1
            if data_index >= len(dates):
                self.popup_bg_canvas.itemconfigure(card["day"], text="-")
                self.popup_bg_canvas.coords(card["icon"], card.get("center_x", 0), card.get("icon_y", 0))
                self._configure_canvas_weather_icon(
                    card["icon"],
                    "unknown",
                    FORECAST_ICON_WIDTH,
                    FORECAST_ICON_HEIGHT,
                )
                self.popup_bg_canvas.itemconfigure(card["temp"], text="--° / --°")
                continue

            forecast_style = resolve_weather_style(
                code_list[data_index] if data_index < len(code_list) else None,
                True,
            )
            high = format_temperature(t_max[data_index] if data_index < len(t_max) else None, self.unit_symbol)
            low = format_temperature(t_min[data_index] if data_index < len(t_min) else None, self.unit_symbol)
            try:
                day_index = datetime.strptime(dates[data_index], "%Y-%m-%d").weekday()
                day_label = WEEKDAY_SHORT_FI.get(day_index, "-")
            except (TypeError, ValueError):
                day_label = "-"

            self.popup_bg_canvas.itemconfigure(card["day"], text=day_label)
            self.popup_bg_canvas.coords(card["icon"], card.get("center_x", 0), card.get("icon_y", 0))
            self._configure_canvas_weather_icon(
                card["icon"],
                forecast_style.icon_key,
                FORECAST_ICON_WIDTH,
                FORECAST_ICON_HEIGHT,
            )
            self.popup_bg_canvas.itemconfigure(card["temp"], text=f"{high} / {low}")

    def _apply_weather(self, place: dict, weather: dict, requested_city: str) -> None:
        validate_weather_payload(weather)
        place_data = _as_dict(place)
        weather_data = _as_dict(weather)
        current = _as_dict(weather_data.get("current"))
        daily = _as_dict(weather_data.get("daily"))
        current_units = _as_dict(weather_data.get("current_units"))
        daily_units = _as_dict(weather_data.get("daily_units"))

        unit_text = _clean_text(current_units.get("temperature_2m")) or f"°{self.unit_symbol}"
        unit_symbol = unit_text.replace("°", "")
        self.unit_symbol = unit_symbol or self.unit_symbol

        style = resolve_weather_style(current.get("weather_code"), _is_daytime(current.get("is_day")))
        refreshed_at = datetime.now()
        now_text = refreshed_at.strftime("%H:%M")
        current_temp = format_temperature(current.get("temperature_2m"), self.unit_symbol)
        city_text = format_city(place_data)

        t_min = _as_list(daily.get("temperature_2m_min"))
        t_max = _as_list(daily.get("temperature_2m_max"))
        daily_rain_prob = _as_list(daily.get("precipitation_probability_max"))
        rain_sum = _as_list(daily.get("precipitation_sum"))
        sunrise_list = _as_list(daily.get("sunrise"))
        sunset_list = _as_list(daily.get("sunset"))

        rain_mm_unit = _clean_text(daily_units.get("precipitation_sum")) or "mm"
        today_high = format_temperature(_sequence_item(t_max), self.unit_symbol)
        today_low = format_temperature(_sequence_item(t_min), self.unit_symbol)
        humidity_pct = format_metric(current.get("relative_humidity_2m"), "%")
        next_hours_rain_prob = max_precipitation_probability_next_hours(weather_data)
        if next_hours_rain_prob is not None:
            today_rain_prob = f"{next_hours_rain_prob}%"
        else:
            today_rain_prob = format_metric(_sequence_item(daily_rain_prob), "%")
        today_rain_mm = format_metric(_sequence_item(rain_sum), f" {rain_mm_unit}", decimals=1)
        wind_speed_ms = format_metric(current.get("wind_speed_10m"), " m/s", decimals=1)
        wind_direction = format_wind_direction(current.get("wind_direction_10m"))
        today_sunrise = format_time_short(_sequence_item(sunrise_list))
        today_sunset = format_time_short(_sequence_item(sunset_list))

        if wind_speed_ms == "-":
            wind_text = "-"
        elif wind_direction == "-":
            wind_text = wind_speed_ms
        else:
            wind_text = f"{wind_speed_ms} ({wind_direction})"

        requested_city_text = _clean_text(requested_city)
        place_name = _clean_text(place_data.get("name"))
        if requested_city_text and place_name and requested_city_text.casefold() == place_name.casefold():
            normalized_city = place_name
        else:
            normalized_city = requested_city_text or place_name or DEFAULT_CITY
        self.latest_place = place_data
        self.latest_weather = weather_data
        self.last_weather_update = refreshed_at
        self.city_var.set(normalized_city)
        city_changed = self.settings.get("city") != normalized_city
        if city_changed:
            self.settings["city"] = normalized_city

        self._apply_current_weather_summary(style, current_temp, city_text, f"Päivitetty {now_text}")
        self._apply_today_detail_metrics(
            condition_label=style.label,
            high_low_text=f"ylin {today_high} / alin {today_low}",
            rain_mm=today_rain_mm,
            rain_probability=today_rain_prob,
            humidity=humidity_pct,
            wind=wind_text,
            sunrise=today_sunrise,
            sunset=today_sunset,
        )

        self.status_var.set("")
        self._update_tray_symbol(style.icon_key, f"{city_text}: {current_temp} {style.label}")
        if _normalize_city_query(self.detail_city_var.get()).casefold() == requested_city_text.casefold():
            self.detail_city_var.set(normalized_city)
        self._apply_forecast_cards(daily)

        self.popup_bg_canvas.itemconfigure(self.footer_label, text=FOOTER_TEXT)
        if city_changed or self._settings_save_pending:
            self._persist_settings()
        self.fetch_in_progress = False
        self._schedule_refresh()
        self._run_pending_city_search()


if __name__ == "__main__":
    app = WeatherWidget()
    app.mainloop()

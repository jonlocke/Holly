from __future__ import annotations

import json
import logging
from urllib import parse as urllib_parse
from urllib import request as urllib_request

logger = logging.getLogger(__name__)


WEATHER_CODE_LABELS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class Plugin:
    id = "weather"
    version = "0.2.0"
    timeout_seconds = 4.0

    def __init__(self):
        self.app_context = None
        self.commands = {"/weather": "Get current weather for a location. Usage: /weather <location>"}
        self.tools = {
            "weather.get_current_weather": {
                "description": "Get the current weather for a user-provided location.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City, town, or place name such as 'London' or 'Seattle, WA'.",
                        }
                    },
                    "required": ["location"],
                },
            }
        }

    def on_load(self, app_context):
        self.app_context = app_context

    def on_unload(self):
        self.app_context = None

    def on_command(self, command, args, context):
        location = " ".join(args).strip()
        if not location:
            return {
                "type": "command_response",
                "command": command,
                "content": "Usage: /weather <location>",
            }

        self._log_invocation("command", location, context)
        weather = self._lookup_weather(location)
        return {
            "type": "command_response",
            "command": command,
            "content": self._format_weather_summary(weather),
            "weather": weather,
        }

    def call_tool(self, tool_name, arguments, context):
        if tool_name != "weather.get_current_weather":
            raise ValueError(f"Unsupported weather tool '{tool_name}'.")

        location = str((arguments or {}).get("location") or "").strip()
        if not location:
            raise ValueError("The weather tool requires a location.")

        self._log_invocation("tool", location, context)
        weather = self._lookup_weather(location)
        return {
            "ok": True,
            "tool_name": tool_name,
            "content": self._format_weather_summary(weather),
            "data": weather,
        }

    def _log_invocation(self, source: str, location: str, context: dict[str, object] | None) -> None:
        logger.info(
            "Weather plugin invoked via %s for location=%r session_id=%s user=%s",
            source,
            location,
            str((context or {}).get("session_id") or "unknown"),
            str((context or {}).get("username") or (context or {}).get("user_id") or "anonymous"),
        )

    def _lookup_weather(self, location: str) -> dict[str, object]:
        geocode_url = self._build_geocode_url(location)
        geocode_payload = self._fetch_json(geocode_url)
        results = geocode_payload.get("results") or []
        if not results:
            raise ValueError(f"No weather location match was found for '{location}'.")

        place = results[0]
        latitude = place.get("latitude")
        longitude = place.get("longitude")
        if latitude is None or longitude is None:
            raise RuntimeError("Weather provider returned an incomplete geocoding response.")

        forecast_url = self._build_forecast_url(float(latitude), float(longitude))
        forecast_payload = self._fetch_json(forecast_url)
        current = forecast_payload.get("current") or {}
        units = forecast_payload.get("current_units") or {}
        if not current:
            raise RuntimeError("Weather provider did not return current conditions.")

        weather_code = int(current.get("weather_code", -1))
        resolved_name = self._place_label(place)
        return {
            "provider": "open-meteo",
            "location": resolved_name,
            "requested_location": location,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "temperature": current.get("temperature_2m"),
            "temperature_unit": units.get("temperature_2m", "C"),
            "apparent_temperature": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "humidity_unit": units.get("relative_humidity_2m", "%"),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_speed_unit": units.get("wind_speed_10m", "km/h"),
            "weather_code": weather_code,
            "weather_summary": WEATHER_CODE_LABELS.get(weather_code, "Unknown conditions"),
        }

    def _build_geocode_url(self, location: str) -> str:
        query = urllib_parse.urlencode(
            {
                "name": location,
                "count": 1,
                "language": "en",
                "format": "json",
            }
        )
        return f"https://geocoding-api.open-meteo.com/v1/search?{query}"

    def _build_forecast_url(self, latitude: float, longitude: float) -> str:
        query = urllib_parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
                "forecast_days": 1,
            }
        )
        return f"https://api.open-meteo.com/v1/forecast?{query}"

    def _fetch_json(self, url: str) -> dict[str, object]:
        validator = (self.app_context or {}).get("validate_outbound_http_url")
        safe_url = validator(url) if callable(validator) else url
        req = urllib_request.Request(
            safe_url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "HollyWeatherPlugin/0.2",
            },
        )
        with urllib_request.urlopen(req, timeout=3.5) as response:  # nosec B310 - URL is validated via app context when available.
            return json.loads(response.read().decode("utf-8", errors="ignore") or "{}")

    def _place_label(self, place: dict[str, object]) -> str:
        parts = []
        for key in ("name", "admin1", "country"):
            value = str(place.get(key) or "").strip()
            if value and value not in parts:
                parts.append(value)
        return ", ".join(parts) or str(place.get("name") or "Unknown location")

    def _format_weather_summary(self, weather: dict[str, object]) -> str:
        return (
            f"{weather['location']}: {weather['weather_summary']}, "
            f"{weather['temperature']}{weather['temperature_unit']} "
            f"(feels like {weather['apparent_temperature']}{weather['temperature_unit']}). "
            f"Humidity {weather['humidity']}{weather['humidity_unit']}, "
            f"wind {weather['wind_speed']} {weather['wind_speed_unit']}."
        )

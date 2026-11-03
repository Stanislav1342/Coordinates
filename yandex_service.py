"""
yandex_service.py — Сервис геокодирования и сравнения координат.

Функционал:
1. Очистка адреса от логистических пометок (подъезд, ворота, рампа) для точного поиска.
2. Геокодирование через HTTP API Яндекс Карт (или Nominatim как резерв).
3. Расчет расстояния (в метрах) между точками по формуле Haversine.
4. Интеллектуальный анализ отклонения:
   - Смещение > 200 м -> ошибка в координатах (требуется обновление в 1С).
   - Смещение <= 200 м -> координаты верны (сбой РЭБ или требуется расширение радиуса).
"""

import math
import os
import re
import urllib.parse
import urllib.request
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GeocodeResult:
    lat: float
    lon: float
    found_address: str
    precision: str = "exact"  # exact, number, street, other
    source: str = "yandex"


def clean_address_for_search(raw_address: str) -> str:
    """
    Очищает адрес от внутренних логистических уточнений,
    которые мешают геокодеру найти дом (подъезды, рампы, строения без номера).
    """
    addr = raw_address
    patterns_to_remove = [
        r",?\s*(?:корп\.?\s*)?подъезд\s*№?\s*\d+",
        r",?\s*подъезд\s*№?\s*\d+",
        r",?\s*(?:ворота|рампа|кпп)\s*№?\s*\d+",
        r",?\s*этаж\s*№?\s*\d+",
        r",?\s*пом(?:ещение)?\.?\s*№?\s*\d+",
        r",?\s*офис\s*№?\s*\d+",
        r",?\s*территория\s*Многофункциональный\s*Логистический\s*Парк",
    ]
    for pattern in patterns_to_remove:
        addr = re.sub(pattern, "", addr, flags=re.IGNORECASE)
    addr = re.sub(r"\s*,\s*,+", ",", addr)
    return re.sub(r"\s+", " ", addr).strip(" ,")


def normalize_address_variants(raw_address: str) -> list[str]:
    """
    Генерирует список вариантов адреса от наиболее подробного к наиболее простому
    для надежного поиска в геокодерах.
    """
    cleaned = clean_address_for_search(raw_address)
    variants = [cleaned]

    # Вариант без индекса
    no_index = re.sub(r"^\d{6},?\s*", "", cleaned).strip(" ,")
    if no_index != cleaned:
        variants.append(no_index)

    # Вариант без микрорайонов ('Северный мкр,', 'мкр. Северный,')
    no_mkr = re.sub(r",?\s*(?:[А-Яа-я0-9\-]+\s+мкр\.?|мкр\.?\s+[А-Яа-я0-9\-]+)", "", no_index, flags=re.IGNORECASE)
    no_mkr = re.sub(r"\s*,\s*,+", ",", no_mkr).strip(" ,")
    if no_mkr not in variants:
        variants.append(no_mkr)

    # Упрощенный вариант: извлечь Город/Район + Улица + Дом
    # Например: 'Домодедово, Логистическая улица, 1/6'
    city_match = re.search(r"([А-Яа-я\-]+(?:\s+г|\s+город|(?<=г\.\s)|(?<=г\s))[А-Яа-я\-]+|[А-Яа-я\-]+(?=\s+г\b))", cleaned, flags=re.IGNORECASE)
    street_match = re.search(r"([А-Яа-я0-9\-\s]+(?:\s+ул|\s+улица|\s+пр-кт|\s+проспект|\s+шоссе|\s+ш|\s+пер|\s+проезд)[А-Яа-я0-9\-\s]*)", cleaned, flags=re.IGNORECASE)
    house_match = re.search(r"(?:д\.?|дом|вл\.?|владение|стр\.?|строение)\s*([0-9]+[0-9а-яА-Я\/\-]*)", cleaned, flags=re.IGNORECASE)

    parts = []
    if city_match:
        city = city_match.group(1).replace("г.", "").replace("г", "").strip()
        parts.append(city)
    if street_match:
        street = street_match.group(1).replace("ул.", "").replace("ул", "").strip()
        parts.append(street)
    if house_match:
        house = house_match.group(1).strip()
        parts.append(house)

    if len(parts) >= 2:
        simple = " ".join(parts)
        if simple not in variants:
            variants.append(simple)

    return variants


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Вычисляет расстояние между двумя точками на сфере Земли в метрах.
    """
    R = 6371000.0  # радиус Земли в метрах
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


class YandexGeocoder:
    """Сервис геокодирования."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("YANDEX_MAPS_API_KEY", "")

    def geocode(self, address: str) -> GeocodeResult:
        """
        Геокодирует адрес.
        Если задан YANDEX_MAPS_API_KEY — использует официальный HTTP API Яндекса.
        Если ключ не задан — использует публичный геокодер OpenStreetMap Nominatim.
        """
        clean_addr = clean_address_for_search(address)

        if self.api_key:
            return self._geocode_yandex_api(clean_addr)
        else:
            return self._geocode_nominatim(clean_addr)

    def _geocode_yandex_api(self, address: str) -> GeocodeResult:
        """Запрос к официальному Yandex Geocoder API."""
        encoded_addr = urllib.parse.quote(address)
        url = (
            f"https://geocode-maps.yandex.ru/1.x/"
            f"?apikey={self.api_key}&geocode={encoded_addr}&format=json&results=1"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "Advantum1CSync/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        members = (
            data.get("response", {})
            .get("GeoObjectCollection", {})
            .get("featureMember", [])
        )
        if not members:
            raise ValueError(f"Адрес не найден в Яндекс Картах: '{address}'")

        geo_obj = members[0]["GeoObject"]
        # В ответе Яндекса порядок "lon lat" (долгота широта) через пробел:
        pos = geo_obj["Point"]["pos"].split()
        lon, lat = float(pos[0]), float(pos[1])
        found_address = geo_obj.get("metaDataProperty", {}).get(
            "GeocoderMetaData", {}
        ).get("text", address)
        precision = (
            geo_obj.get("metaDataProperty", {})
            .get("GeocoderMetaData", {})
            .get("precision", "other")
        )

        return GeocodeResult(
            lat=lat,
            lon=lon,
            found_address=found_address,
            precision=precision,
            source="yandex_api",
        )

    def _geocode_nominatim(self, address: str) -> GeocodeResult:
        """Публичный fallback-геокодер (OSM), если ключ Яндекса не указан."""
        variants = normalize_address_variants(address)
        last_error = None

        for query_str in variants:
            encoded_addr = urllib.parse.quote(query_str)
            url = (
                f"https://nominatim.openstreetmap.org/search"
                f"?q={encoded_addr}&format=json&addressdetails=1&limit=1"
            )
            req = urllib.request.Request(
                url, headers={"User-Agent": "AdvantumCoordinateChecker/1.0 (internal tool)"}
            )
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if data:
                    item = data[0]
                    lat = float(item["lat"])
                    lon = float(item["lon"])
                    found_address = item.get("display_name", address)
                    return GeocodeResult(
                        lat=lat,
                        lon=lon,
                        found_address=found_address,
                        precision=item.get("type", "exact"),
                        source="nominatim_osm",
                    )
            except Exception as e:
                last_error = e

        raise ValueError(
            f"Адрес не найден в геокодере (проверены варианты: {variants}). Ошибка: {last_error}"
        )


def evaluate_coordinates(
    original_lat: float | None,
    original_lon: float | None,
    target_lat: float,
    target_lon: float,
    distance_threshold_m: float = 200.0,
) -> dict:
    """
    Сравнивает исходные координаты (из 1С / Advantum) с эталонными.
    Возвращает статус и рекомендации.
    """
    if original_lat is None or original_lon is None:
        return {
            "status": "MISSING_COORDINATES",
            "distance_m": None,
            "action": "UPDATE_1C",
            "reason": "Координаты в системе отсутствуют или равны нулю.",
        }

    dist_m = haversine_distance(original_lat, original_lon, target_lat, target_lon)

    if dist_m > distance_threshold_m:
        return {
            "status": "COORDINATE_MISMATCH",
            "distance_m": round(dist_m, 1),
            "action": "UPDATE_1C",
            "reason": (
                f"Смещение составляет {dist_m:.1f} м (> {distance_threshold_m:.0f} м). "
                f"Точка в системе стоит не на объекте! Требуется исправление в 1С."
            ),
        }
    else:
        return {
            "status": "COORDINATES_OK",
            "distance_m": round(dist_m, 1),
            "action": "KEEP_COORDINATES",
            "reason": (
                f"Координаты верные (смещение всего {dist_m:.1f} м). "
                f"Несработка вызвана сбоем GPS (РЭБ/спуфинг) или узким радиусом зоны."
            ),
        }

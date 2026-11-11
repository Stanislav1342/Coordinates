"""
audit_service.py — Интеллектуальный аудит и диагностика причин неотбитых точек (Advantum <-> 1С).

Определяет точные причины несработки телематики для каждой точки:
1. ВОДИТЕЛЯ НЕ БЫЛО НА ТОЧКЕ — автомобиль не приближался к объекту (дистанция > 1.2 км).
2. НЕПРАВИЛЬНЫЕ КООРДИНАТЫ В ЕИС — координаты точки в ЕИС смещены более чем на 200 м
   от реального здания по Яндекс Картам, при этом водитель был у реального здания.
3. НЕДОСТАТОЧНЫЙ РАДИУС ЗОНЫ В ЕИС — водитель подъехал к объекту (на 100–500 м),
   но остановился перед шлагбаумом / на парковке и не попал в стандартный радиус зоны.
4. НАРУШЕНИЕ ВРЕМЕННОГО ОКНА (ОПОЗДАНИЕ) — водитель был на точке, но заехал раньше или позже
   планового интервала доставки (в Advantum статус «Непопадание в окно»).
5. СБОЙ GPS / РЭБ — координаты верные, но трекер потерял спутники или сбросил геопозицию.
"""

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from yandex_service import YandexGeocoder, haversine_distance

logger = logging.getLogger(__name__)


@dataclass
class PointAudit:
    index: int
    code: str
    name: str
    address: str
    operation: str  # Погрузка / Разгрузка
    status_raw: str  # OK, NEAR, FAIL
    status_title: str  # Пройдена / Непопадание в окно / Не пройдена
    plan_start: str
    plan_finish: str
    fact_start: str
    fact_finish: str
    time_on_point: str
    adv_lat: Optional[float]
    adv_lon: Optional[float]
    geo_lat: Optional[float] = None
    geo_lon: Optional[float] = None
    geo_address: str = ""
    dist_adv_to_geo: Optional[float] = None
    min_dist_to_geo: Optional[float] = None
    closest_time_geo: str = ""
    min_dist_to_adv: Optional[float] = None
    closest_time_adv: str = ""
    verdict: str = ""
    reason: str = ""
    recommended_action: str = ""
    recommended_radius: Optional[int] = None
    needs_1c_update: bool = False


@dataclass
class ShipmentAudit:
    shipment_id: str
    driver_fio: str
    driver_phone: str
    vehicle_num: str
    vehicle_id: str
    status: str
    created_date: str
    total_points: int
    ok_count: int
    near_count: int
    fail_count: int
    gps_points_count: int
    points: List[PointAudit] = field(default_factory=list)


def audit_shipment(driver, shipment_id: str, geocoder: YandexGeocoder) -> ShipmentAudit:
    """
    Выполняет полный аудит рейса через нативный REST API Advantum и геокодер Яндекс Карт.
    Считывает рейс, все точки доставки и полный GPS-трек автомобиля за день рейса.
    """
    fetch_js = f"""
    return (async function() {{
        var authStr = localStorage.getItem('auth_data');
        if (!authStr) return {{ error: 'auth_data not found in localStorage' }};
        var token = '';
        try {{
            var parsed = JSON.parse(authStr);
            token = parsed.authData ? parsed.authData.access_token : '';
        }} catch(e) {{
            return {{ error: 'failed to parse auth_data: ' + String(e) }};
        }}
        
        var headers = {{
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/json'
        }};
        
        // 1. Инфо о рейсе
        var shipResp = await fetch('/api/v1/shipments/{shipment_id}', {{ headers: headers }});
        var shipment = shipResp.ok ? await shipResp.json() : null;
        
        // 2. Все точки рейса (независимо от скролла и пагинации!)
        var ptsResp = await fetch('/api/v1/shipments/{shipment_id}/points', {{ headers: headers }});
        var points = ptsResp.ok ? await ptsResp.json() : [];
        
        // 3. Полный GPS-трек машины
        var track = [];
        if (shipment && shipment.vehicleId) {{
            var dateStr = shipment.createdDate || (shipment.factStartTime ? shipment.factStartTime.substring(0, 10) : '');
            if (!dateStr) {{
                var now = new Date();
                dateStr = now.toISOString().substring(0, 10);
            }}
            var trackUrl = '/api/v1/vehicleLocations?vehicleId=' + shipment.vehicleId + 
                           '&from=' + dateStr + 'T00:00:00Z&to=' + dateStr + 'T23:59:59Z';
            var trackResp = await fetch(trackUrl, {{ headers: headers }});
            if (trackResp.ok) {{
                track = await trackResp.json();
            }}
        }}
        
        return {{ shipment: shipment, points: points, track: track }};
    }})();
    """
    data = driver.execute_script(fetch_js)
    if not data or data.get("error"):
        raise RuntimeError(f"Ошибка получения данных рейса {shipment_id} через API: {data.get('error') if data else 'Empty response'}")

    shipment_obj = data.get("shipment") or {}
    points_list = data.get("points") or []
    track_list = data.get("track") or []

    shipment_audit = ShipmentAudit(
        shipment_id=str(shipment_id),
        driver_fio=shipment_obj.get("driverFio") or "Не указан",
        driver_phone=shipment_obj.get("driverPhone") or "",
        vehicle_num=shipment_obj.get("vehicleGosNum") or "Не указан",
        vehicle_id=str(shipment_obj.get("vehicleId") or ""),
        status=shipment_obj.get("status") or "UNKNOWN",
        created_date=shipment_obj.get("createdDate") or "",
        total_points=len(points_list),
        ok_count=sum(1 for p in points_list if p.get("tag") == "OK"),
        near_count=sum(1 for p in points_list if p.get("tag") == "NEAR"),
        fail_count=sum(1 for p in points_list if p.get("tag") == "FAIL"),
        gps_points_count=len(track_list),
    )

    for p in points_list:
        seq = p.get("sequenceNumber", 0)
        loc = p.get("location") or {}
        loc_name = loc.get("locationName", "")
        code = p.get("customerPointExternalId", "")
        address = loc.get("address", "")
        operations = p.get("operations") or []
        operation = "Погрузка" if "LOAD" in operations else "Разгрузка"
        tag = p.get("tag", "")

        pt_coord = loc.get("point") or {}
        adv_lat = pt_coord.get("latitude")
        adv_lon = pt_coord.get("longitude")

        off_int = p.get("offsetInterval") or {}
        plan_start = (off_int.get("startTime") or {}).get("time", "")
        plan_finish = (off_int.get("finishTime") or {}).get("time", "")

        fact_start = p.get("telematicsStartTime") or ""
        fact_finish = p.get("telematicsFinishTime") or ""
        time_on_point = p.get("timeOnPoint") or "—"

        status_title = "Пройдена (В окне)" if tag == "OK" else ("Непопадание в окно" if tag == "NEAR" else "Не пройдена")

        p_audit = PointAudit(
            index=seq + 1,
            code=code,
            name=loc_name,
            address=address,
            operation=operation,
            status_raw=tag,
            status_title=status_title,
            plan_start=plan_start,
            plan_finish=plan_finish,
            fact_start=fact_start,
            fact_finish=fact_finish,
            time_on_point=time_on_point,
            adv_lat=adv_lat,
            adv_lon=adv_lon,
        )

        # 1. Если точка отбита вовремя — всё идеально
        if tag == "OK":
            p_audit.verdict = "✓ Пройдена вовремя"
            p_audit.reason = f"Телематический заезд зарегистрирован вовремя (в {fact_start})."
            p_audit.recommended_action = "Корректировка не требуется."
            p_audit.needs_1c_update = False
            shipment_audit.points.append(p_audit)
            continue

        # 2. Если точка отбита, но вне окна (NEAR — Непопадание в окно)
        if tag == "NEAR":
            p_audit.verdict = "⚠ Нарушение временного окна (Опоздание)"
            p_audit.reason = (
                f"Водитель был на объекте ({fact_start}), но прибыл вне планового интервала доставки "
                f"(План: {plan_start}—{plan_finish})."
            )
            p_audit.recommended_action = "Геокоординаты верные. Изменение координат не требуется. Требуется согласование времени с логистикой."
            p_audit.needs_1c_update = False
            shipment_audit.points.append(p_audit)
            continue

        # 3. Точка со статусом FAIL (Не пройдена) — глубокий геометрический анализ трека и геокодера
        try:
            geo_res = geocoder.geocode(address)
            p_audit.geo_lat = geo_res.lat
            p_audit.geo_lon = geo_res.lon
            p_audit.geo_address = geo_res.found_address
        except Exception as e:
            logger.error("Геокодирование адреса '%s' не удалось: %s", address, e)
            p_audit.verdict = "✗ Ошибка геокодирования адреса"
            p_audit.reason = f"Яндекс Карты не смогли найти адрес: {e}"
            p_audit.recommended_action = "Проверить корректность написания адреса вручную."
            shipment_audit.points.append(p_audit)
            continue

        # Дистанция между точкой ЕИС и реальным зданием
        if adv_lat and adv_lon and p_audit.geo_lat and p_audit.geo_lon:
            p_audit.dist_adv_to_geo = haversine_distance(adv_lat, adv_lon, p_audit.geo_lat, p_audit.geo_lon)

        # Сканируем весь GPS-трек автомобиля за день
        min_dist_to_geo = 999999.0
        closest_time_geo = ""
        min_dist_to_adv = 999999.0
        closest_time_adv = ""

        for pt in track_list:
            t_lat = pt.get("lat")
            t_lon = pt.get("lon")
            t_time = pt.get("time") or ""

            if p_audit.geo_lat and p_audit.geo_lon:
                dg = haversine_distance(t_lat, t_lon, p_audit.geo_lat, p_audit.geo_lon)
                if dg < min_dist_to_geo:
                    min_dist_to_geo = dg
                    closest_time_geo = t_time

            if adv_lat and adv_lon:
                da = haversine_distance(t_lat, t_lon, adv_lat, adv_lon)
                if da < min_dist_to_adv:
                    min_dist_to_adv = da
                    closest_time_adv = t_time

        p_audit.min_dist_to_geo = min_dist_to_geo if min_dist_to_geo < 900000 else None
        p_audit.closest_time_geo = closest_time_geo
        p_audit.min_dist_to_adv = min_dist_to_adv if min_dist_to_adv < 900000 else None
        p_audit.closest_time_adv = closest_time_adv

        # -------------------------------------------------------------
        # ОПРЕДЕЛЕНИЕ ТОЧНОЙ ПРИЧИНЫ НЕОТБИТОЙ ТОЧКИ
        # -------------------------------------------------------------
        # Сценарий А: Водителя вообще не было на объекте (дистанция > 1200 м)
        if p_audit.min_dist_to_geo is not None and p_audit.min_dist_to_geo > 1200:
            dist_km = p_audit.min_dist_to_geo / 1000.0
            p_audit.verdict = "✗ ВОДИТЕЛЯ НЕ БЫЛО НА ТОЧКЕ"
            p_audit.reason = (
                f"По GPS-треку автомобиль не подъезжал к адресу ближе {dist_km:.1f} км "
                f"(ближайшая отметка трека в {closest_time_geo})."
            )
            p_audit.recommended_action = "Координаты верные. Водитель не выполнил заезд на объект. Корректировка в 1С НЕ требуется."
            p_audit.needs_1c_update = False

        # Сценарий Б: Неправильные координаты в базе ЕИС (смещение > 200 м, а водитель был у здания)
        elif p_audit.dist_adv_to_geo is not None and p_audit.dist_adv_to_geo > 200 and p_audit.min_dist_to_geo is not None and p_audit.min_dist_to_geo <= 350:
            p_audit.verdict = "⚠ НЕПРАВИЛЬНЫЕ КООРДИНАТЫ В БАЗЕ ЕИС"
            p_audit.reason = (
                f"Точка в ЕИС стоит со смещением {p_audit.dist_adv_to_geo:.0f} м от реального здания. "
                f"Водитель подъезжал именно к зданию (дистанция {p_audit.min_dist_to_geo:.0f} м в {closest_time_geo}), "
                f"но не попал в ошибочную геозону ЕИС."
            )
            p_audit.recommended_action = (
                f"РЕКОМЕНДАЦИЯ: Обновить координаты в 1С на реальное здание: "
                f"Широта={p_audit.geo_lat:.8f}, Долгота={p_audit.geo_lon:.8f}"
            )
            p_audit.needs_1c_update = True

        # Сценарий В: Недостаточный радиус зоны (шлагбаум, парковка, ТЦ)
        elif p_audit.min_dist_to_geo is not None and 100 < p_audit.min_dist_to_geo <= 600:
            rec_rad = int(math.ceil((p_audit.min_dist_to_geo + 60) / 50.0) * 50)
            p_audit.recommended_radius = rec_rad
            p_audit.verdict = "⚠ НЕДОСТАТОЧНЫЙ РАДИУС ЗОНЫ В ЕИС"
            p_audit.reason = (
                f"Водитель подъезжал к объекту на {p_audit.min_dist_to_geo:.0f} м ({closest_time_geo}), "
                f"но парковался перед шлагбаумом / на стоянке и не вошел в текущую геозону 1С."
            )
            p_audit.recommended_action = f"РЕКОМЕНДАЦИЯ: Увеличить радиус зоны доставки в 1С до {rec_rad} м."
            p_audit.needs_1c_update = False

        # Сценарий Г: Сбой трекера / РЭБ или кратковременный проезд
        else:
            p_audit.verdict = "⚠ СБОЙ ТЕЛЕМАТИКИ / РЭБ"
            dist_info = f"{p_audit.min_dist_to_geo:.0f} м" if p_audit.min_dist_to_geo is not None else "нет данных"
            p_audit.reason = (
                f"Смещение координат ЕИС составляет всего {p_audit.dist_adv_to_geo or 0:.0f} м (координаты верные). "
                f"Сближение автомобиля: {dist_info}. Время стоянки не зафиксировано или потерян GPS сигнал."
            )
            p_audit.recommended_action = "Координаты верные. Требуется ручная проверка накладной / трека водителем."
            p_audit.needs_1c_update = False

        shipment_audit.points.append(p_audit)

    return shipment_audit


def generate_audit_report_text(audits: List[ShipmentAudit]) -> str:
    """Формирует красивый, подробный текстовый отчет аудита рейсов."""
    lines = []
    lines.append("=" * 80)
    lines.append("       ЭКСПЕРТНЫЙ АУДИТ ПРИЧИН НЕОТБИТЫХ ТОЧЕК (ADVANTUM <-> 1С)")
    lines.append(f"       Дата формирования отчета: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    lines.append("=" * 80)

    for sa in audits:
        lines.append("")
        lines.append("=" * 80)
        lines.append(f" РЕЙС №{sa.shipment_id}")
        lines.append("=" * 80)
        lines.append(f" • Водитель:          {sa.driver_fio} ({sa.driver_phone})")
        lines.append(f" • Автомобиль:        {sa.vehicle_num} (ID: {sa.vehicle_id})")
        lines.append(f" • Статус рейса:      {sa.status}")
        lines.append(f" • Всего точек:       {sa.total_points}")
        lines.append(f" • Отбиты вовремя:    {sa.ok_count}")
        lines.append(f" • Опоздания (окно):  {sa.near_count}")
        lines.append(f" • НЕ ПРОЙДЕНЫ:       {sa.fail_count}")
        lines.append(f" • GPS точек трека:   {sa.gps_points_count}")
        lines.append("-" * 80)

        for p in sa.points:
            lines.append(f"\n [ТОЧКА №{p.index}] {p.name} (Код: {p.code or 'нет'})")
            lines.append(f"   Адрес:          {p.address}")
            lines.append(f"   Операция:       {p.operation}")
            lines.append(f"   Статус в ЕИС:   {p.status_title}")
            lines.append(f"   План доставки:  {p.plan_start or '—'} ... {p.plan_finish or '—'}")
            lines.append(f"   Факт телематики:{p.fact_start or '—'} ... {p.fact_finish or '—'} (Стоянка: {p.time_on_point})")
            if p.adv_lat and p.adv_lon:
                lines.append(f"   Координаты ЕИС: {p.adv_lat:.8f}, {p.adv_lon:.8f}")

            if p.status_raw != "OK":
                if p.geo_lat and p.geo_lon:
                    lines.append(f"   Яндекс Карты:   {p.geo_lat:.8f}, {p.geo_lon:.8f}")
                    if p.dist_adv_to_geo is not None:
                        lines.append(f"   Смещение ЕИС:   {p.dist_adv_to_geo:.1f} м от реального здания")
                if p.min_dist_to_geo is not None:
                    lines.append(f"   Мин. сближение: {p.min_dist_to_geo:.1f} м (время отметки трека: {p.closest_time_geo or '—'})")

            lines.append(f"   ВЕРДИКТ:        {p.verdict}")
            lines.append(f"   ПРИЧИНА:        {p.reason}")
            lines.append(f"   ДЕЙСТВИЕ:       {p.recommended_action}")

    # Сводная итоговая таблица
    lines.append("\n" + "=" * 80)
    lines.append("                      СВОДНАЯ ИТОГОВАЯ ТАБЛИЦА")
    lines.append("=" * 80)
    lines.append(f" {'№':<3} | {'Рейс':<10} | {'Точек':<6} | {'В окне':<7} | {'Опоздание':<10} | {'Не пройдена':<12} | {'К изменению в 1С':<16}")
    lines.append("-" * 80)
    for idx, sa in enumerate(audits, start=1):
        to_update = sum(1 for p in sa.points if p.needs_1c_update)
        lines.append(
            f" {idx:<3} | {sa.shipment_id:<10} | {sa.total_points:<6} | {sa.ok_count:<7} | {sa.near_count:<10} | {sa.fail_count:<12} | {to_update:<16}"
        )
    lines.append("=" * 80)
    return "\n".join(lines)


def save_audit_report_to_file(report_text: str, filename: Optional[str] = None) -> str:
    """Сохраняет отчет аудита в файл на диске."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if not filename:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"audit_report_{timestamp}.txt"
    filepath = os.path.join(base_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n[Отчет сохранен]: {filepath}")
    return filepath

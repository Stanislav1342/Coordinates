"""
audit_service.py — Интеллектуальный аудит и диагностика причин неотбитых точек (Advantum <-> 1С).

Определяет точные причины несработки телематики для каждой точки:
1. ЛОЖНОЕ ОПОЗДАНИЕ В ADVANTUM (ПОВТОРНЫЙ ТРАНЗИТНЫЙ ПРОЕЗД) — водитель выгрузил точку
   вовремя в плановом окне, но позже проехал мимо, и Advantum ошибочно перезаписал
   время прибытия на время транзитного проезда со статусом "Непопадание в окно".
2. ОШИБКА АДРЕСА В ЕИС / ЗАЕЗД НА ФАКТИЧЕСКИЙ СКЛАД — в ЕИС указан неверный адрес/дом,
   но водитель выполнил реальную стоянку на фактическом складе клиента неподалеку (400–1200 м).
3. НЕПРАВИЛЬНЫЕ КООРДИНАТЫ В ЕИС — координаты точки в ЕИС смещены более чем на 200 м
   от реального здания, при этом водитель подъезжал именно к зданию.
4. НЕТОЧНОСТЬ КООРДИНАТ В ЕИС (ПРОЕЗЖАЯ ЧАСТЬ / ПАРКОВКА) — точка стоит на дороге
   со смещением 30–200 м от здания.
5. НЕДОСТАТОЧНЫЙ РАДИУС ЗОНЫ В ЕИС — водитель подъехал к объекту (на 100–450 м),
   но стоял перед шлагбаумом / на парковке ТЦ и не попал в стандартный радиус зоны.
6. НАРУШЕНИЕ ВРЕМЕННОГО ОКНА (РЕАЛЬНОЕ ОПОЗДАНИЕ) — водитель действительно прибыл позже
   планового интервала доставки.
7. ЗАЕЗД НЕ ЗАФИКСИРОВАН / СБОЙ GPS (РЭБ / ПРОСТРЕЛ) — приближение по имеющемуся треку
   не зафиксировано, но из-за прострелов/разрывов трека требуется подтверждение по ТТН.
8. ВОДИТЕЛЬ НЕ ПОСЕЩАЛ ТОЧКУ — автомобиль по непрерывному треку следовал по другому маршруту.
"""

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from yandex_service import YandexGeocoder, clean_address_for_search, haversine_distance

logger = logging.getLogger(__name__)

# Московский часовой пояс (UTC+3)
MSK_TZ = timezone(timedelta(hours=3))


def to_msk_dt(dt_val: Any) -> Optional[datetime]:
    """Преобразует строку даты/времени в datetime с московским часовым поясом (UTC+3)."""
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        return dt_val.astimezone(MSK_TZ) if dt_val.tzinfo else dt_val.replace(tzinfo=MSK_TZ)
    if not isinstance(dt_val, str):
        return None
    s = dt_val.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(MSK_TZ)
        if "+" in s[10:] or "-" in s[10:]:
            return datetime.fromisoformat(s).astimezone(MSK_TZ)
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=MSK_TZ)
    except Exception:
        return None


def format_msk(dt_val: Any, include_date: bool = False) -> str:
    """Форматирует дату/время в строку по Московскому времени (МСК)."""
    dt = to_msk_dt(dt_val)
    if not dt:
        return str(dt_val) if dt_val else "—"
    if include_date:
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    return dt.strftime("%H:%M:%S")


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
    coord_status: str = ""  # ACCURATE, MODERATE_OFFSET, CRITICAL_OFFSET
    min_dist_to_geo: Optional[float] = None
    closest_time_geo: str = ""
    min_dist_to_adv: Optional[float] = None
    closest_time_adv: str = ""
    detected_stop_lat: Optional[float] = None
    detected_stop_lon: Optional[float] = None
    detected_stop_duration: Optional[float] = None
    detected_stop_time: str = ""
    detected_stop_dist: Optional[float] = None
    actual_visit_in_window: Optional[str] = None
    is_false_late: bool = False
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
    shipment_date: str
    total_points: int
    ok_count: int
    near_count: int
    fail_count: int
    false_late_count: int = 0
    gps_points_count: int = 0
    stops_count: int = 0
    gps_gaps_detected: bool = False
    points: List[PointAudit] = field(default_factory=list)


def extract_vehicle_stops(track_pts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Выделяет стоянки автомобиля из массива GPS-отметок трека.
    Стоянкой считается интервал со скоростью < 5 км/ч длительностью >= 1.5 минут.
    """
    stops = []
    current_stop = []

    for pt in track_pts:
        speed = pt.get("speed", 0) or 0
        if speed < 5:
            current_stop.append(pt)
        else:
            if current_stop:
                try:
                    t0 = to_msk_dt(current_stop[0]["time"])
                    t1 = to_msk_dt(current_stop[-1]["time"])
                    if t0 and t1:
                        dur_min = (t1 - t0).total_seconds() / 60.0
                        if dur_min >= 1.5:
                            avg_lat = sum(p["lat"] for p in current_stop) / len(current_stop)
                            avg_lon = sum(p["lon"] for p in current_stop) / len(current_stop)
                            stops.append({
                                "start_dt": t0,
                                "end_dt": t1,
                                "start": format_msk(t0),
                                "end": format_msk(t1),
                                "duration_min": round(dur_min, 1),
                                "lat": avg_lat,
                                "lon": avg_lon,
                                "pts_count": len(current_stop),
                            })
                except Exception:
                    pass
                current_stop = []

    if current_stop:
        try:
            t0 = to_msk_dt(current_stop[0]["time"])
            t1 = to_msk_dt(current_stop[-1]["time"])
            if t0 and t1:
                dur_min = (t1 - t0).total_seconds() / 60.0
                if dur_min >= 1.5:
                    avg_lat = sum(p["lat"] for p in current_stop) / len(current_stop)
                    avg_lon = sum(p["lon"] for p in current_stop) / len(current_stop)
                    stops.append({
                        "start_dt": t0,
                        "end_dt": t1,
                        "start": format_msk(t0),
                        "end": format_msk(t1),
                        "duration_min": round(dur_min, 1),
                        "lat": avg_lat,
                        "lon": avg_lon,
                        "pts_count": len(current_stop),
                    })
        except Exception:
            pass

    return stops


def detect_gps_gaps(track_pts: List[Dict[str, Any]]) -> bool:
    """
    Проверяет трек на наличие существенных разрывов связи (> 15 минут)
    или резких прострелов координат (скорость > 160 км/ч).
    """
    if len(track_pts) < 2:
        return True

    for i in range(1, len(track_pts)):
        try:
            p0 = track_pts[i - 1]
            p1 = track_pts[i]
            t0 = to_msk_dt(p0["time"])
            t1 = to_msk_dt(p1["time"])
            if t0 and t1:
                dt_sec = (t1 - t0).total_seconds()
                if dt_sec > 900:  # Разрыв более 15 минут
                    return True
                dist_m = haversine_distance(p0["lat"], p0["lon"], p1["lat"], p1["lon"])
                if dt_sec > 0 and (dist_m / dt_sec * 3.6) > 160.0:
                    return True
        except Exception:
            pass
    return False


def audit_shipment(driver, shipment_id: str, geocoder: YandexGeocoder) -> ShipmentAudit:
    """
    Выполняет полный интеллектуальный аудит рейса через нативный REST API Advantum,
    геокодер Яндекс Карт и расширенный геометрический анализ трека и стоянок.
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
        
        // 3. Определение реальной даты выполнения рейса (date/factStartTime/firstPointStartTime)
        var actualDate = '';
        if (shipment) {{
            actualDate = shipment.date || 
                         (shipment.factStartTime ? shipment.factStartTime.substring(0, 10) : '') ||
                         (shipment.firstPointStartTime ? shipment.firstPointStartTime.substring(0, 10) : '') ||
                         (shipment.firstPointPassStartTime ? shipment.firstPointPassStartTime.substring(0, 10) : '') ||
                         (shipment.createdDate || '');
                         
            if (!actualDate) {{
                var now = new Date();
                actualDate = now.toISOString().substring(0, 10);
            }}
        }}
        
        // 4. Запрос GPS-трека (проверяем тягач, а при отсутствии отметок — полуприцеп!)
        var vehicleIdsToTry = [];
        if (shipment) {{
            if (shipment.vehicleId) vehicleIdsToTry.push(shipment.vehicleId);
            if (shipment.trailerId && !vehicleIdsToTry.includes(shipment.trailerId)) {{
                vehicleIdsToTry.push(shipment.trailerId);
            }}
            if (Array.isArray(shipment.vehicleIds)) {{
                for (var vid of shipment.vehicleIds) {{
                    if (!vehicleIdsToTry.includes(vid)) vehicleIdsToTry.push(vid);
                }}
            }}
            if (Array.isArray(shipment.trailerIds)) {{
                for (var tid of shipment.trailerIds) {{
                    if (!vehicleIdsToTry.includes(tid)) vehicleIdsToTry.push(tid);
                }}
            }}
        }}
        
        var track = [];
        var usedTrackId = '';
        for (var vid of vehicleIdsToTry) {{
            var trackUrl = '/api/v1/vehicleLocations?vehicleId=' + vid + 
                           '&from=' + actualDate + 'T00:00:00Z&to=' + actualDate + 'T23:59:59Z';
            var trackResp = await fetch(trackUrl, {{ headers: headers }});
            if (trackResp.ok) {{
                var pts = await trackResp.json();
                if (Array.isArray(pts) && pts.length > 0) {{
                    track = pts;
                    usedTrackId = String(vid);
                    break;
                }}
            }}
        }}
        
        return {{ shipment: shipment, points: points, track: track, actualDate: actualDate, usedTrackId: usedTrackId }};
    }})();
    """
    data = driver.execute_script(fetch_js)
    if not data or data.get("error"):
        raise RuntimeError(f"Ошибка получения данных рейса {shipment_id} через API: {data.get('error') if data else 'Empty response'}")

    shipment_obj = data.get("shipment") or {}
    points_list = data.get("points") or []
    track_list = data.get("track") or []
    actual_date = data.get("actualDate") or shipment_obj.get("date") or ""

    # Парсим отметки трека в Московское время
    parsed_track = []
    for pt in track_list:
        t_msk = to_msk_dt(pt.get("time"))
        if t_msk and "lat" in pt and "lon" in pt:
            parsed_track.append({
                "lat": pt["lat"],
                "lon": pt["lon"],
                "speed": pt.get("speed", 0) or 0,
                "time_msk": t_msk,
                "time_str": format_msk(t_msk),
            })

    # Выделяем все стоянки автомобиля и проверяем разрывы трека
    vehicle_stops = extract_vehicle_stops(track_list)
    has_gaps = detect_gps_gaps(track_list)

    # Для каждой стоянки определяем минимальное расстояние до ближайшей точки рейса,
    # чтобы стоянка у соседней аптеки не приписывалась другой точке
    for s in vehicle_stops:
        min_d = 999999.0
        for pt_item in points_list:
            loc_pt = (pt_item.get("location") or {}).get("point") or {}
            pt_lat = loc_pt.get("latitude")
            pt_lon = loc_pt.get("longitude")
            if pt_lat and pt_lon:
                d = haversine_distance(s["lat"], s["lon"], pt_lat, pt_lon)
                if d < min_d:
                    min_d = d
        s["min_pt_dist"] = min_d

    shipment_audit = ShipmentAudit(
        shipment_id=str(shipment_id),
        driver_fio=shipment_obj.get("driverFio") or "Не указан",
        driver_phone=shipment_obj.get("driverPhone") or "",
        vehicle_num=shipment_obj.get("vehicleGosNum") or "Не указан",
        vehicle_id=str(shipment_obj.get("vehicleId") or ""),
        status=shipment_obj.get("status") or "UNKNOWN",
        shipment_date=actual_date,
        total_points=len(points_list),
        ok_count=sum(1 for p in points_list if p.get("tag") == "OK"),
        near_count=sum(1 for p in points_list if p.get("tag") == "NEAR"),
        fail_count=sum(1 for p in points_list if p.get("tag") == "FAIL"),
        gps_points_count=len(track_list),
        stops_count=len(vehicle_stops),
        gps_gaps_detected=has_gaps,
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

        # Плановый интервал доставки
        off_int = p.get("offsetInterval") or {}
        plan_start_raw = (off_int.get("startTime") or {}).get("time", "")
        plan_finish_raw = (off_int.get("finishTime") or {}).get("time", "")
        if not plan_start_raw and p.get("interval"):
            inv = p.get("interval") or {}
            plan_start_raw = inv.get("startTime", "")
            plan_finish_raw = inv.get("finishTime", "")

        plan_t0 = to_msk_dt(plan_start_raw)
        plan_t1 = to_msk_dt(plan_finish_raw)
        plan_start_str = format_msk(plan_t0)
        plan_finish_str = format_msk(plan_t1)

        # Фактические данные телематики Advantum
        fact_start_raw = p.get("telematicsStartTime") or ""
        fact_finish_raw = p.get("telematicsFinishTime") or ""
        fact_t0 = to_msk_dt(fact_start_raw)
        fact_t1 = to_msk_dt(fact_finish_raw)
        fact_start_str = format_msk(fact_t0)
        fact_finish_str = format_msk(fact_t1)
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
            plan_start=plan_start_str,
            plan_finish=plan_finish_str,
            fact_start=fact_start_str,
            fact_finish=fact_finish_str,
            time_on_point=time_on_point,
            adv_lat=adv_lat,
            adv_lon=adv_lon,
        )

        # -------------------------------------------------------------
        # 1. ГЕОКОДИРОВАНИЕ ЯНДЕКС КАРТ ДЛЯ ВСЕХ ТОЧЕК (OK, NEAR, FAIL)
        # -------------------------------------------------------------
        try:
            geo_res = geocoder.geocode(address)
            p_audit.geo_lat = geo_res.lat
            p_audit.geo_lon = geo_res.lon
            p_audit.geo_address = geo_res.found_address
            if adv_lat and adv_lon and p_audit.geo_lat and p_audit.geo_lon:
                p_audit.dist_adv_to_geo = haversine_distance(adv_lat, adv_lon, p_audit.geo_lat, p_audit.geo_lon)
                if p_audit.dist_adv_to_geo > 200:
                    p_audit.coord_status = "CRITICAL_OFFSET"
                elif p_audit.dist_adv_to_geo >= 30:
                    p_audit.coord_status = "MODERATE_OFFSET"
                else:
                    p_audit.coord_status = "ACCURATE"
        except Exception as e:
            logger.warning("Геокодирование адреса '%s' не удалось: %s", address, e)

        # -------------------------------------------------------------
        # 2. СКАН ТРЕКА: МАКСИМАЛЬНОЕ СБЛИЖЕНИЕ И РЕАЛЬНЫЕ СТОЯНКИ У ТОЧКИ
        # -------------------------------------------------------------
        min_dist_to_geo = 999999.0
        closest_time_geo = ""
        min_dist_to_adv = 999999.0
        closest_time_adv = ""

        for pt in parsed_track:
            t_lat = pt["lat"]
            t_lon = pt["lon"]
            t_str = pt["time_str"]

            da = haversine_distance(t_lat, t_lon, adv_lat, adv_lon) if adv_lat and adv_lon else 999999.0
            dg = haversine_distance(t_lat, t_lon, p_audit.geo_lat, p_audit.geo_lon) if p_audit.geo_lat and p_audit.geo_lon else 999999.0

            if da < min_dist_to_adv:
                min_dist_to_adv = da
                closest_time_adv = t_str
            if dg < min_dist_to_geo:
                min_dist_to_geo = dg
                closest_time_geo = t_str

        p_audit.min_dist_to_geo = min_dist_to_geo if min_dist_to_geo < 900000 else None
        p_audit.closest_time_geo = closest_time_geo
        p_audit.min_dist_to_adv = min_dist_to_adv if min_dist_to_adv < 900000 else None
        p_audit.closest_time_adv = closest_time_adv

        # Ищем реальные непрерывные стоянки (speed < 5 км/ч >= 1.5 мин) строго в радиусе 150 м от точки ЕИС
        # (или от Яндекса, только если расхождение с ЕИС <= 200 м)
        has_confirmed_eis_stop = False
        own_stops = []
        for s in vehicle_stops:
            d_adv = haversine_distance(s["lat"], s["lon"], adv_lat, adv_lon) if adv_lat and adv_lon else 999999.0
            if d_adv <= 150.0:
                has_confirmed_eis_stop = True
            d_ref = d_adv
            if (
                p_audit.geo_lat
                and p_audit.geo_lon
                and p_audit.dist_adv_to_geo is not None
                and p_audit.dist_adv_to_geo <= 200.0
            ):
                d_geo = haversine_distance(s["lat"], s["lon"], p_audit.geo_lat, p_audit.geo_lon)
                d_ref = min(d_adv, d_geo)

            if d_ref <= 150.0 and d_adv <= (s.get("min_pt_dist", 999999.0) + 25.0):
                own_stops.append((d_ref, s))

        own_stops.sort(key=lambda item: item[1]["start_dt"])

        # Если водитель стоял у координат ЕИС (>1.5 мин, <=150м), а Яндекс выдал центр промзоны/ТЦ >200м — доверяем треку
        if has_confirmed_eis_stop and p_audit.dist_adv_to_geo is not None and p_audit.dist_adv_to_geo > 200:
            p_audit.coord_status = "CONFIRMED_BY_TRACK"

        # Ищем стоянку в плановое окно доставки (именно реальную стоянку, а не транзитный проезд!)
        in_window_stop = None
        earliest_own_stop = own_stops[0] if own_stops else None
        if plan_t0 and plan_t1:
            for d_ref, s in own_stops:
                # Водитель прибыл на стоянку до окончания планового окна (или выехал после его начала)
                if s["start_dt"] <= plan_t1 and s["end_dt"] >= plan_t0:
                    in_window_stop = (d_ref, s)
                    break

        # -------------------------------------------------------------
        # 3. ПОИСК СТОЯНОК ВОДИТЕЛЯ В РАДИУСЕ ДО 3500 М (ДЛЯ СКЛАДОВ)
        # -------------------------------------------------------------
        best_stop = None
        min_stop_dist = 999999.0
        best_stop_is_window_match = False
        target_ref_lat = p_audit.geo_lat or adv_lat
        target_ref_lon = p_audit.geo_lon or adv_lon

        if target_ref_lat and target_ref_lon:
            for s in vehicle_stops:
                ds = haversine_distance(s["lat"], s["lon"], target_ref_lat, target_ref_lon)
                if adv_lat and adv_lon:
                    ds_adv = haversine_distance(s["lat"], s["lon"], adv_lat, adv_lon)
                    ds = min(ds, ds_adv)

                is_window_match = False
                s_t0 = s.get("start_dt")
                s_t1 = s.get("end_dt")
                if plan_t0 and plan_t1 and s_t0 and s_t1:
                    w_start = plan_t0 - timedelta(minutes=60)
                    w_end = plan_t1 + timedelta(minutes=60)
                    if not (s_t1 < w_start or s_t0 > w_end):
                        is_window_match = True

                if is_window_match and ds <= 3500:
                    if not best_stop_is_window_match or ds < min_stop_dist:
                        min_stop_dist = ds
                        best_stop = s
                        best_stop_is_window_match = True
                elif not best_stop_is_window_match and ds < min_stop_dist:
                    min_stop_dist = ds
                    best_stop = s

        if best_stop and min_stop_dist <= 3500:
            p_audit.detected_stop_lat = best_stop["lat"]
            p_audit.detected_stop_lon = best_stop["lon"]
            p_audit.detected_stop_duration = best_stop["duration_min"]
            p_audit.detected_stop_dist = min_stop_dist
            p_audit.detected_stop_time = f"{best_stop['start']}–{best_stop['end']}"

        # -------------------------------------------------------------
        # 4. ВЕРДИКТ И ПРИЧИНЫ
        # -------------------------------------------------------------
        # СЦЕНАРИЙ 1: Статус OK (отбита вовремя в Advantum)
        if tag == "OK":
            if p_audit.coord_status == "CRITICAL_OFFSET":
                p_audit.verdict = "✓ Пройдена вовремя (⚠ Критическое смещение координат в ЕИС)"
                p_audit.reason = (
                    f"Телематический заезд зарегистрирован вовремя (в {fact_start_str} МСК). "
                    f"Однако координаты точки в ЕИС смещены на {p_audit.dist_adv_to_geo:.0f} м от реального здания. "
                    f"При изменении маршрута или радиуса точка может перестать отбиваться."
                )
                p_audit.recommended_action = (
                    f"РЕКОМЕНДАЦИЯ: Скорректировать координаты в 1С на реальное здание: "
                    f"Широта={p_audit.geo_lat:.8f}, Долгота={p_audit.geo_lon:.8f}"
                )
                p_audit.needs_1c_update = True
            elif p_audit.coord_status == "MODERATE_OFFSET":
                p_audit.verdict = "✓ Пройдена вовремя (⚠ Неточность координат в ЕИС)"
                p_audit.reason = (
                    f"Телематический заезд зарегистрирован вовремя (в {fact_start_str} МСК). "
                    f"Координаты точки в ЕИС смещены на {p_audit.dist_adv_to_geo:.0f} м от здания "
                    f"(точка стоит на проезжей части / парковке)."
                )
                p_audit.recommended_action = (
                    f"Рекомендуется уточнить координаты в 1С по зданию: "
                    f"{p_audit.geo_lat:.8f}, {p_audit.geo_lon:.8f} (во избежание ложных несработок телематики)."
                )
                p_audit.needs_1c_update = False
            elif p_audit.coord_status == "CONFIRMED_BY_TRACK":
                p_audit.verdict = "✓ Пройдена вовремя"
                p_audit.reason = (
                    f"Телематический заезд зарегистрирован вовремя (в {fact_start_str} МСК) и подтвержден стоянкой у координат ЕИС "
                    f"(поиск Яндекса указал на центр района/ТЦ со смещением {p_audit.dist_adv_to_geo:.0f} м)."
                )
                p_audit.recommended_action = "Корректировка не требуется (координаты ЕИС подтверждены стоянкой)."
                p_audit.needs_1c_update = False
            else:
                p_audit.verdict = "✓ Пройдена вовремя"
                p_audit.reason = f"Телематический заезд зарегистрирован вовремя (в {fact_start_str} МСК). Координаты в ЕИС точные."
                p_audit.recommended_action = "Корректировка не требуется."
                p_audit.needs_1c_update = False

            shipment_audit.points.append(p_audit)
            continue

        # СЦЕНАРИЙ 2: Статус NEAR (Непопадание в окно / Опоздание)
        if tag == "NEAR":
            if in_window_stop:
                # Водитель фактически выгрузился вовремя (непрерывная стоянка в плановом окне), а Advantum записал повторный проезд!
                d_ref, s = in_window_stop
                p_audit.is_false_late = True
                shipment_audit.false_late_count += 1
                p_audit.actual_visit_in_window = f"{s['start']}–{s['end']} МСК (стоянка {s['duration_min']} мин, удаление {d_ref:.0f} м)"
                p_audit.verdict = "✓ ФАКТИЧЕСКИ ВОВРЕМЯ (ЛОЖНОЕ ОПОЗДАНИЕ В ADVANTUM)"
                p_audit.reason = (
                    f"Фактическая доставка выполнена ВОВРЕМЯ: водитель выполнил реальную стоянку у объекта в {s['start']}–{s['end']} МСК "
                    f"(стоянка {s['duration_min']} мин, сближение {d_ref:.0f} м), что внутри планового интервала "
                    f"доставки ({plan_start_str}—{plan_finish_str} МСК). "
                    f"В {fact_start_str} МСК система Advantum зафиксировала повторный транзитный проезд автомобиля "
                    f"и ошибочно приняла его за время прибытия."
                )
                if p_audit.coord_status == "MODERATE_OFFSET":
                    p_audit.reason += f" При этом в ЕИС координаты смещены на {p_audit.dist_adv_to_geo:.0f} м от здания (точка на проезжей части / парковке)."
                    p_audit.recommended_action = (
                        f"Фактическая доставка выполнена в срок (снять штраф за опоздание). "
                        f"Рекомендуется скорректировать координаты в 1С: {p_audit.geo_lat:.8f}, {p_audit.geo_lon:.8f}."
                    )
                else:
                    p_audit.recommended_action = "Фактическая доставка выполнена в срок. В логистических отчетах и штрафах зафиксировать своевременную выгрузку."
                p_audit.needs_1c_update = False
            else:
                # Реальное опоздание (проверяем, не сдвинул ли Advantum реальное время стоянки на более поздний транзитный проезд)
                earlier_note = ""
                if earliest_own_stop and fact_t0:
                    ed_ref, es = earliest_own_stop
                    if (fact_t0 - es["start_dt"]).total_seconds() > 180:
                        earlier_note = (
                            f" Реальная стоянка у объекта зафиксирована раньше: {es['start']}–{es['end']} МСК "
                            f"({es['duration_min']} мин, удаление {ed_ref:.0f} м), а {fact_start_str} МСК — повторный проезд."
                        )

                p_audit.verdict = "⚠ Нарушение временного окна (Опоздание)"
                p_audit.reason = (
                    f"Водитель прибыл на объект в {fact_start_str} МСК вне планового интервала доставки "
                    f"(План: {plan_start_str}—{plan_finish_str} МСК).{earlier_note}"
                )
                if p_audit.coord_status == "CONFIRMED_BY_TRACK":
                    p_audit.reason += (
                        f" Координаты ЕИС подтверждены фактической стоянкой у объекта "
                        f"(Яндекс указал на центр района/ТЦ со смещением {p_audit.dist_adv_to_geo:.0f} м)."
                    )
                    p_audit.recommended_action = "Координаты подтверждены стоянкой. Требуется согласование времени с логистикой."
                elif p_audit.coord_status in ("MODERATE_OFFSET", "CRITICAL_OFFSET"):
                    p_audit.reason += f" Координаты точки в ЕИС смещены на {p_audit.dist_adv_to_geo:.0f} м от здания (точка на проезжей части / парковке)."
                    p_audit.recommended_action = (
                        f"Согласовать время с логистикой/клиентом. "
                        f"Рекомендуется скорректировать координаты в 1С на реальное здание: {p_audit.geo_lat:.8f}, {p_audit.geo_lon:.8f}."
                    )
                else:
                    p_audit.recommended_action = "Геокоординаты верные. Изменение координат не требуется. Требуется согласование времени с логистикой."
                p_audit.needs_1c_update = False

            shipment_audit.points.append(p_audit)
            continue

        # СЦЕНАРИЙ 3: Статус FAIL (Не пройдена)
        if p_audit.detected_stop_dist is not None and 350 < p_audit.detected_stop_dist <= 3500:
            window_info = f" в плановое время доставки ({p_audit.detected_stop_time} МСК)" if best_stop_is_window_match else f" (время {p_audit.detected_stop_time} МСК)"
            p_audit.verdict = "⚠ ОШИБКА АДРЕСА В ЕИС (ЗАЕЗД НА ФАКТИЧЕСКИЙ СКЛАД КЛИЕНТА)"
            p_audit.reason = (
                f"В базе ЕИС указан неверный адрес: '{address}' (удаление {p_audit.detected_stop_dist:.0f} м). "
                f"Однако водитель выполнил реальную погрузку/стоянку длительностью {p_audit.detected_stop_duration} мин{window_info} "
                f"по координатам {p_audit.detected_stop_lat:.8f}, {p_audit.detected_stop_lon:.8f}. "
                f"По данным карт здесь находится фактический склад клиента. Точка не отбилась из-за неверного адреса/координат в ЕИС."
            )
            p_audit.recommended_action = (
                f"РЕКОМЕНДАЦИЯ: Обновить координаты в 1С на фактическую стоянку/склад: "
                f"Широта={p_audit.detected_stop_lat:.8f}, Долгота={p_audit.detected_stop_lon:.8f} (уточнить текстовый адрес с клиентом)."
            )
            p_audit.geo_lat = p_audit.detected_stop_lat
            p_audit.geo_lon = p_audit.detected_stop_lon
            p_audit.needs_1c_update = True

        elif p_audit.detected_stop_dist is not None and 100 < p_audit.detected_stop_dist <= 350:
            rec_rad = int(math.ceil((p_audit.detected_stop_dist + 60) / 50.0) * 50)
            p_audit.recommended_radius = rec_rad
            p_audit.verdict = "⚠ НЕДОСТАТОЧНЫЙ РАДИУС ЗОНЫ В ЕИС (ШЛАГБАУМ / ПАРКОВКА)"
            p_audit.reason = (
                f"Водитель выполнил стоянку ({p_audit.detected_stop_duration} мин в {p_audit.detected_stop_time} МСК) "
                f"на удалении {p_audit.detected_stop_dist:.0f} м от объекта (перед шлагбаумом / на парковке), "
                f"но не попал в стандартный радиус зоны ЕИС."
            )
            p_audit.recommended_action = f"РЕКОМЕНДАЦИЯ: Увеличить радиус зоны доставки в 1С до {rec_rad} м."
            p_audit.needs_1c_update = False

        elif (
            p_audit.dist_adv_to_geo is not None
            and p_audit.dist_adv_to_geo > 200
            and p_audit.min_dist_to_geo is not None
            and p_audit.min_dist_to_geo <= 350
        ):
            p_audit.verdict = "⚠ НЕПРАВИЛЬНЫЕ КООРДИНАТЫ В БАЗЕ ЕИС"
            p_audit.reason = (
                f"Точка в ЕИС стоит со смещением {p_audit.dist_adv_to_geo:.0f} м от реального здания. "
                f"Водитель подъезжал к зданию (дистанция {p_audit.min_dist_to_geo:.0f} м в {closest_time_geo} МСК), "
                f"но не попал в ошибочную геозону ЕИС."
            )
            p_audit.recommended_action = (
                f"РЕКОМЕНДАЦИЯ: Обновить координаты в 1С на реальное здание: "
                f"Широта={p_audit.geo_lat:.8f}, Долгота={p_audit.geo_lon:.8f}"
            )
            p_audit.needs_1c_update = True

        elif has_gaps or len(track_list) < 50:
            dist_val = p_audit.min_dist_to_adv or p_audit.min_dist_to_geo or 0.0
            dist_km = dist_val / 1000.0
            p_audit.verdict = "⚠ ЗАЕЗД НЕ ЗАФИКСИРОВАН (ВОЗМОЖЕН СБОЙ GPS / РЭБ / ПРОСТРЕЛ ТРЕКА)"
            p_audit.reason = (
                f"По имеющимся отметкам трека автомобиль не приближался ближе {dist_km:.1f} км. "
                f"При этом на треке зафиксированы разрывы связи / прострелы координат (потеря сигнала спутников / РЭБ). "
                f"Нельзя гарантировать отсутствие заезда — требуется сверка с бумажной накладной / водителем."
            )
            p_audit.recommended_action = "Координаты верные. Не изменять 1С без подтверждения факта доставки по накладной."
            p_audit.needs_1c_update = False

        elif p_audit.min_dist_to_adv is not None and p_audit.min_dist_to_adv > 1500:
            dist_km = p_audit.min_dist_to_adv / 1000.0
            p_audit.verdict = "✗ ВОДИТЕЛЬ НЕ ПОСЕЩАЛ ТОЧКУ"
            p_audit.reason = (
                f"По непрерывному GPS-треку автомобиль не подъезжал к объекту ближе {dist_km:.1f} км "
                f"(ближайшая отметка трека в {p_audit.closest_time_adv or closest_time_geo} МСК)."
            )
            p_audit.recommended_action = "Координаты верные. Водитель не выполнил заезд на объект. Корректировка в 1С НЕ требуется."
            p_audit.needs_1c_update = False

        else:
            p_audit.verdict = "⚠ КРАТКОВРЕМЕННЫЙ ПРОЕЗД / СБОЙ ТЕЛЕМАТИКИ"
            dist_info = f"{p_audit.min_dist_to_adv or p_audit.min_dist_to_geo or 0:.0f} м"
            p_audit.reason = (
                f"Координаты точки в ЕИС верные (отклонение {p_audit.dist_adv_to_geo or 0:.0f} м). "
                f"Сближение автомобиля: {dist_info}. Время стоянки не зафиксировано или потерян сигнал трекера."
            )
            p_audit.recommended_action = "Координаты верные. Требуется ручная проверка накладной / путевого листа."
            p_audit.needs_1c_update = False

        shipment_audit.points.append(p_audit)

    return shipment_audit


def generate_audit_report_text(audits: List[ShipmentAudit]) -> str:
    """Формирует структурированный экспертный отчет аудита рейсов."""
    lines = []
    lines.append("=" * 80)
    lines.append("       ЭКСПЕРТНЫЙ АУДИТ ПРИЧИН НЕОТБИТЫХ ТОЧЕК (ADVANTUM <-> 1С)")
    lines.append(f"       Дата формирования отчета: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} (МСК)")
    lines.append("=" * 80)

    for sa in audits:
        lines.append("")
        lines.append("=" * 80)
        lines.append(f" РЕЙС №{sa.shipment_id}")
        lines.append("=" * 80)
        lines.append(f" • Дата рейса:        {sa.shipment_date}")
        lines.append(f" • Водитель:          {sa.driver_fio} ({sa.driver_phone})")
        lines.append(f" • Автомобиль:        {sa.vehicle_num} (ID: {sa.vehicle_id})")
        lines.append(f" • Статус рейса:      {sa.status}")
        lines.append(f" • Всего точек:       {sa.total_points}")
        lines.append(f" • Отбиты вовремя:    {sa.ok_count}")
        near_desc = f"{sa.near_count}"
        if sa.false_late_count > 0:
            near_desc += f" (из них ЛОЖНЫХ из-за повторных проездов: {sa.false_late_count})"
        lines.append(f" • Опоздания:         {near_desc}")
        lines.append(f" • НЕ ПРОЙДЕНЫ:       {sa.fail_count}")
        lines.append(f" • GPS отметок трека: {sa.gps_points_count}")
        lines.append(f" • Стоянок водителя:  {sa.stops_count}")
        if sa.gps_gaps_detected:
            lines.append(" • Внимание по GPS:   Обнаружены разрывы трека / прострелы координат (РЭБ)")
        lines.append("-" * 80)

        for p in sa.points:
            lines.append(f"\n [ТОЧКА №{p.index}] {p.name} (Код: {p.code or 'нет'})")
            lines.append(f"   Адрес ЕИС:      {p.address}")
            lines.append(f"   Операция:       {p.operation}")
            lines.append(f"   Статус в ЕИС:   {p.status_title}")
            lines.append(f"   План доставки:  {p.plan_start} — {p.plan_finish} (МСК)")
            lines.append(f"   Факт телематики:{p.fact_start} — {p.fact_finish} (МСК) (Стоянка: {p.time_on_point})")
            if p.adv_lat and p.adv_lon:
                lines.append(f"   Координаты ЕИС: {p.adv_lat:.8f}, {p.adv_lon:.8f}")

            # Геокоординаты эталонного здания в Яндекс Картах и смещение
            if p.geo_lat and p.geo_lon:
                lines.append(f"   Яндекс Карты:   {p.geo_lat:.8f}, {p.geo_lon:.8f}")
                if p.dist_adv_to_geo is not None:
                    if p.coord_status == "CONFIRMED_BY_TRACK":
                        offset_desc = "координаты ЕИС подтверждены стоянкой у объекта"
                    elif p.dist_adv_to_geo < 30:
                        offset_desc = "точно на здании"
                    elif p.dist_adv_to_geo <= 200:
                        offset_desc = "на проезжей части / парковке"
                    else:
                        offset_desc = "КРИТИЧЕСКОЕ СМЕЩЕНИЕ"
                    lines.append(f"   Смещение здания:{p.dist_adv_to_geo:.1f} м от точки ЕИС ({offset_desc})")

            # Если выявлено ложное опоздание из-за повторного проезда
            if p.is_false_late and p.actual_visit_in_window:
                lines.append(f"   ФАКТИЧ. ВЫГРУЗКА:{p.actual_visit_in_window} — В ПЛАНОВОМ ОКНЕ")

            if p.detected_stop_dist is not None and p.status_raw == "FAIL":
                lines.append(
                    f"   ФАКТ. СТОЯНКА:  {p.detected_stop_lat:.8f}, {p.detected_stop_lon:.8f} "
                    f"({p.detected_stop_duration} мин, интервал {p.detected_stop_time} МСК, удаление {p.detected_stop_dist:.1f} м)"
                )
            elif p.min_dist_to_geo is not None and p.status_raw == "FAIL":
                lines.append(f"   Мин. сближение: {p.min_dist_to_geo:.1f} м (время отметки трека: {p.closest_time_geo or '—'} МСК)")

            lines.append(f"   ВЕРДИКТ:        {p.verdict}")
            lines.append(f"   ПРИЧИНА:        {p.reason}")
            lines.append(f"   ДЕЙСТВИЕ:       {p.recommended_action}")

    # Сводная итоговая таблица
    lines.append("\n" + "=" * 80)
    lines.append("                      СВОДНАЯ ИТОГОВАЯ ТАБЛИЦА")
    lines.append("=" * 80)
    lines.append(
        f" {'№':<3} | {'Рейс':<10} | {'Точек':<6} | {'В окне':<7} | {'Опоздание':<10} | {'Ложное опозд.':<13} | {'Не пройдена':<12} | {'К изм. в 1С':<12}"
    )
    lines.append("-" * 80)
    for idx, sa in enumerate(audits, start=1):
        to_update = sum(1 for p in sa.points if p.needs_1c_update)
        lines.append(
            f" {idx:<3} | {sa.shipment_id:<10} | {sa.total_points:<6} | {sa.ok_count:<7} | {sa.near_count:<10} | {sa.false_late_count:<13} | {sa.fail_count:<12} | {to_update:<12}"
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
    return filepath

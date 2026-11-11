"""
run.py — Главный запускаемый скрипт аудита и диагностики рейсов Advantum и синхронизации с 1С.

Поддерживает:
1. Графическое окно ввода (GUI) для пакетной обработки нескольких рейсов:
     python run.py
   или принудительно:
     python run.py --gui

2. Пакетный запуск через командную строку:
     python run.py --trip 15181951 15181921
     python run.py --trip 15181951,15181921 --apply-1c

Режимы работы:
- [ПО УМОЛЧАНИЮ] Формат экспертного отчета (Audit & Diagnostics):
  Скрипт проводит глубокий геометрический анализ через нативный API Advantum:
  * Проверяет статус всех точек рейса (без пропусков из-за скролла таблиц).
  * Сканирует полный GPS-трек автомобиля за день рейса (тысячи отметок).
  * Определяет точную причину неотбитой точки:
      - Водителя не было на объекте (дистанция > 1.2 км) -> 1С НЕ трогаем!
      - Неправильные координаты в базе ЕИС (смещение > 200 м, водитель был у здания).
      - Недостаточный радиус зоны (водитель подъезжал на 100-600 м, шлагбаум/парковка).
      - Нарушение временного окна (опоздание водителя).
      - Сбой телематики / РЭБ.
  * Формирует подробный отчет в консоль и сохраняет в текстовый файл audit_report_*.txt.

- [СИНХРОНИЗАЦИЯ С 1С] (--apply-1c):
  Вносит изменения в 1С:Предприятие ИСКЛЮЧИТЕЛЬНО для точек, где доказана
  ошибка координат в базе ЕИС (при фактическом заезде водителя к зданию).
"""

import argparse
import datetime
import logging
import sys
import time
from typing import List, Optional

from advantum_service import AdvantumService
from audit_service import (
    PointAudit,
    ShipmentAudit,
    audit_shipment,
    generate_audit_report_text,
    save_audit_report_to_file,
)
from browser import create_driver, login_to_advantum
from config import load_config
from gui import parse_trips_input, show_batch_input_dialog
from onec_service import get_onec_service
from yandex_service import YandexGeocoder
from utils import wait_overlays_gone

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Advantum1CSync")


def parse_date(date_str: str) -> datetime.date:
    """Парсит дату в формате ДД.ММ.ГГГГ."""
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d.%m.%Y").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Неверный формат даты '{date_str}'. Используйте ДД.ММ.ГГГГ")


def main():
    parser = argparse.ArgumentParser(
        description="Интеллектуальный аудит неотбитых точек рейсов и диагностика причин (Advantum <-> 1С)"
    )
    parser.add_argument(
        "--trip",
        nargs="*",
        default=None,
        help="Один или несколько номеров рейсов (например, --trip 15181951 15181921 или --trip 15181951,15181921)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Принудительно открыть графическое окно ввода рейсов и параметров",
    )
    parser.add_argument(
        "--date-from",
        type=parse_date,
        default=datetime.date.today() - datetime.timedelta(days=7),
        help="Дата начала периода (ДД.ММ.ГГГГ). По умолчанию: 7 дней назад",
    )
    parser.add_argument(
        "--date-to",
        type=parse_date,
        default=datetime.date.today(),
        help="Дата окончания периода (ДД.ММ.ГГГГ). По умолчанию: сегодня",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=None,
        help="Установить радиус зоны (м) в 1С при обновлении (например, 300)",
    )
    parser.add_argument(
        "--apply-1c",
        action="store_true",
        help="Применить рекомендованные изменения в 1С (только для точек, где доказана ошибка координат ЕИС)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Принудительно включить режим только аудита и отчета без изменения 1С",
    )
    parser.add_argument(
        "--no-recalc",
        action="store_true",
        help="Не запускать пересчет телематики в Advantum после обновления 1С",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Запустить браузер в фоновом (headless) режиме",
    )

    args = parser.parse_args()

    # 1. Определение списка рейсов и параметров (через GUI или CLI)
    trips: List[str] = []
    date_from: datetime.date = args.date_from
    date_to: datetime.date = args.date_to
    radius: Optional[int] = args.radius
    no_recalc: bool = args.no_recalc
    dry_run: bool = True  # По умолчанию безопасный режим аудита

    if args.gui or not args.trip:
        initial_trips = args.trip if args.trip else None
        gui_res = show_batch_input_dialog(
            default_trips=initial_trips,
            default_date_from=datetime.datetime.combine(args.date_from, datetime.time.min),
            default_date_to=datetime.datetime.combine(args.date_to, datetime.time.min),
            default_radius=args.radius,
        )
        if not gui_res:
            print("\n[Отмена] Графическое окно закрыто. Запуск отменен.")
            return

        trips = gui_res["trips"]
        d_from = gui_res["date_from"]
        d_to = gui_res["date_to"]
        date_from = d_from.date() if isinstance(d_from, datetime.datetime) else d_from
        date_to = d_to.date() if isinstance(d_to, datetime.datetime) else d_to
        radius = gui_res["radius"]
        dry_run = gui_res["dry_run"]
        no_recalc = gui_res["no_recalc"]
    else:
        raw_trips_str = " ".join(args.trip)
        trips = parse_trips_input(raw_trips_str)
        if args.apply_1c:
            dry_run = False
        if args.dry_run is not None:
            dry_run = args.dry_run

    if not trips:
        print("\n[Ошибка] Не указано ни одного корректного номера рейса. Завершение работы.")
        return

    # 2. Загрузка конфигурации
    config = load_config()
    if args.headless:
        config.headless = True

    print("\n" + "=" * 78)
    print(" АВТОМАТИЗАЦИЯ АУДИТА И ДИАГНОСТИКИ РЕЙСОВ (ADVANTUM <-> 1С)")
    print("=" * 78)
    print(f" Рейсов к аудиту ({len(trips)}):  {', '.join(trips[:8])}{' ...' if len(trips) > 8 else ''}")
    print(f" Режим работы:            {'[ТОЛЬКО АУДИТ И ОТЧЕТ (Безопасный)]' if dry_run else '[СИНХРОНИЗАЦИЯ С 1С (Внесение правок)]'}")
    if radius:
        print(f" Радиус зоны в 1С:        {radius} м")
    if no_recalc:
        print(f" Пересчет телематики:     Отключен (--no-recalc)")
    print("=" * 78 + "\n")

    # 3. Инициализация сервисов
    geocoder = YandexGeocoder()
    onec = None
    if not dry_run:
        try:
            onec = get_onec_service(config)
        except Exception as e:
            logger.warning("Не удалось инициализировать 1С: %s. Переход в режим аудита.", e)
            dry_run = True

    driver = None
    audits: List[ShipmentAudit] = []

    try:
        # 4. Запуск браузера и подключение к Advantum
        driver = create_driver(config, headless=config.headless)
        wait = login_to_advantum(driver, config)
        advantum = AdvantumService(driver, wait, config)

        # 5. Выполнение аудита каждого рейса через API и трекинг
        for trip_idx, trip_num in enumerate(trips, start=1):
            print("\n" + "=" * 78)
            print(f" [{trip_idx}/{len(trips)}] АУДИТ РЕЙСА №{trip_num}...")
            print("=" * 78)

            try:
                shipment_audit = audit_shipment(driver, trip_num, geocoder)
                audits.append(shipment_audit)

                print(f" [Данные] Водитель:    {shipment_audit.driver_fio} ({shipment_audit.driver_phone})")
                print(f" [Данные] Автомобиль:  {shipment_audit.vehicle_num} (ID: {shipment_audit.vehicle_id})")
                print(f" [Данные] Точек всего: {shipment_audit.total_points} | Отбиты: {shipment_audit.ok_count} | Опоздания: {shipment_audit.near_count} | НЕ ПРОЙДЕНЫ: {shipment_audit.fail_count}")
                print(f" [Данные] GPS-трек:    {shipment_audit.gps_points_count} отметок положения автомобиля")

                # Выводим в лог детали по всем проблемным точкам
                non_ok_points = [p for p in shipment_audit.points if p.status_raw != "OK"]
                if not non_ok_points:
                    print(f" [Итог] Все точки рейса №{trip_num} успешно пройдены вовремя!")
                else:
                    for p in non_ok_points:
                        print("\n" + "-" * 78)
                        print(f" ТОЧКА №{p.index} [{p.code or 'нет кода'}]: {p.name}")
                        print(f"   Адрес:     {p.address}")
                        print(f"   Статус:    {p.status_title}")
                        if p.adv_lat and p.adv_lon:
                            print(f"   Координаты ЕИС:   {p.adv_lat:.8f}, {p.adv_lon:.8f}")
                        if p.geo_lat and p.geo_lon:
                            print(f"   Яндекс Карты:     {p.geo_lat:.8f}, {p.geo_lon:.8f} (смещение: {p.dist_adv_to_geo:.1f} м)")
                        if p.min_dist_to_geo is not None:
                            print(f"   Мин. сближение:   {p.min_dist_to_geo:.1f} м ({p.closest_time_geo or '—'})")
                        print(f"   ВЕРДИКТ:   {p.verdict}")
                        print(f"   ПРИЧИНА:   {p.reason}")
                        print(f"   ДЕЙСТВИЕ:  {p.recommended_action}")

            except Exception as e:
                logger.error("Ошибка при аудите рейса №%s: %s", trip_num, e)
                continue

        # 6. Внесение изменений в 1С (только если отключен dry_run)
        if not dry_run and onec is not None:
            total_1c_updated = 0
            for sa in audits:
                needs_update = [p for p in sa.points if p.needs_1c_update]
                if not needs_update:
                    continue

                print("\n" + "=" * 78)
                print(f" КОРРЕКТИРОВКА 1С ДЛЯ РЕЙСА №{sa.shipment_id} (Точек к обновлению: {len(needs_update)})")
                print("=" * 78)

                trip_updated_count = 0
                for p in needs_update:
                    target_rad = p.recommended_radius or radius
                    print(f" [1С] Обновление точки [{p.code}]: {p.name} -> {p.geo_lat:.8f}, {p.geo_lon:.8f}")
                    try:
                        success = onec.update_coordinates(
                            code=p.code,
                            address=p.address,
                            lat=p.geo_lat,
                            lon=p.geo_lon,
                            radius=target_rad,
                            client_name=p.name,
                        )
                        if success:
                            trip_updated_count += 1
                            total_1c_updated += 1
                    except Exception as e:
                        logger.error("Ошибка обновления 1С для точки %s: %s", p.code, e)

                # Пересчет телематики в Advantum для этого рейса
                if trip_updated_count > 0 and not no_recalc:
                    print(f"\n [Advantum] Пересчет телематики для рейса №{sa.shipment_id}...")
                    try:
                        if "control/shipments" not in driver.current_url:
                            driver.get("https://atms.advantum.ru/#/control/shipments")
                            time.sleep(2.5)
                            wait_overlays_gone(driver, timeout=8)
                        advantum.find_and_select_trip(sa.shipment_id)
                        advantum.recalculate_telematics(trip_number=sa.shipment_id)
                    except Exception as e:
                        logger.warning("Не удалось запустить пересчет в Advantum: %s", e)

        # 7. Генерация и сохранение полного экспертного отчета
        if audits:
            report_text = generate_audit_report_text(audits)
            print("\n\n" + report_text + "\n")
            report_file = save_audit_report_to_file(report_text)
            print(f"[Успех] Полный текстовый отчет сохранен в файл: {report_file}")
        else:
            print("\n[Внимание] Данные аудита отсутствуют (рейсы не найдены).")

        if not args.headless:
            input("\n[Аудит завершен] Нажмите Enter для закрытия браузера (или закройте окно вручную)...")

    except KeyboardInterrupt:
        print("\n[Прервано пользователем]")
    except Exception as e:
        logger.exception("Критическая ошибка выполнения: %s", e)
    finally:
        if driver is not None:
            print("[Завершение] Закрытие браузера...")
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()

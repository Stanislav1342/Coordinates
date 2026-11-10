"""
run.py — Главный запускаемый скрипт синхронизации Advantum и 1С:Предприятие.

Поддерживает:
1. Графическое окно ввода (GUI) для пакетной обработки нескольких рейсов:
     python run.py
   или принудительно:
     python run.py --gui

2. Пакетный или одиночный запуск через командную строку:
     python run.py --trip 15053328 15053329 --date-from 20.10.2026 --date-to 30.10.2026
     python run.py --trip 15053328,15053329

Оптимизации скорости:
- Фильтр дат в календаре Advantum выставляется ОДИН раз в самом начале.
- Для каждого рейса скрипт только вводит его номер в поиск Advantum.
- Раздел «Адреса доставки» в 1С открывается по прямой ссылке e1cib (Shift+F11) один раз.
- Фильтр «Организация: ООО "ФК ПУЛЬС"» в 1С устанавливается ОДИН раз на первой точке;
  для всех последующих точек и рейсов 1С сразу ищет номер точки (МСК...).
"""

import argparse
import datetime
import logging
import sys
import time
from typing import List, Optional

from advantum_service import AdvantumService
from browser import create_driver, login_to_advantum
from config import load_config
from gui import parse_trips_input, show_batch_input_dialog
from onec_service import get_onec_service
from yandex_service import YandexGeocoder, evaluate_coordinates
from utils import wait_overlays_gone
from selenium.webdriver.common.by import By

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
        description="Автоматическая проверка и корректировка координат рейсов (Advantum -> Яндекс Карты -> 1С)"
    )
    parser.add_argument(
        "--trip",
        nargs="*",
        default=None,
        help="Один или несколько номеров рейсов в Advantum (например, --trip 15053328 15053329 или --trip 15053328,15053329)",
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
        "--dry-run",
        action="store_true",
        help="Только аудит: проверить точки и показать отклонения, без записи в 1С и пересчета",
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
    dry_run: bool = args.dry_run
    no_recalc: bool = args.no_recalc

    if args.gui or not args.trip:
        # Если рейсы не переданы в командной строке или указан флаг --gui — открываем графическое окно
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
        # Извлекаем рейсы из аргументов командной строки
        raw_trips_str = " ".join(args.trip)
        trips = parse_trips_input(raw_trips_str)

    if not trips:
        print("\n[Ошибка] Не указано ни одного корректного номера рейса. Завершение работы.")
        return

    # 2. Загрузка конфигурации
    config = load_config()
    if args.headless:
        config.headless = True

    print("\n" + "=" * 76)
    print(" АВТОМАТИЗАЦИЯ АУДИТА И КОРРЕКТИРОВКИ КООРДИНАТ (ADVANTUM <-> 1С)")
    print("=" * 76)
    print(f" Рейсов к обработке ({len(trips)}): {', '.join(trips[:8])}{' ...' if len(trips) > 8 else ''}")
    print(f" Период в Advantum:       {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}")
    print(f" Режим работы:            {'[ТОЛЬКО АУДИТ (Dry-run)]' if dry_run else '[ПОЛНАЯ СИНХРОНИЗАЦИЯ]'}")
    if radius:
        print(f" Радиус зоны в 1С:        {radius} м")
    if no_recalc:
        print(f" Пересчет телематики:     Отключен (--no-recalc)")
    print("=" * 76 + "\n")

    # 3. Инициализация сервисов
    geocoder = YandexGeocoder()
    onec = get_onec_service(config)

    driver = None
    summary_data = []

    try:
        # 4. Запуск браузера и вход в Advantum
        driver = create_driver(config, headless=config.headless)
        wait = login_to_advantum(driver, config)
        advantum = AdvantumService(driver, wait, config)

        # 5. ОДНОКРАТНАЯ установка периода дат в календаре Advantum (Рейсы -> Все -> Календарь)
        # Все последующие поиски рейсов будут выполняться в рамках этого установленного периода!
        advantum.prepare_shipments_page(date_from, date_to)
        main_handle = driver.current_window_handle

        # 6. Последовательная обработка каждого рейса из входного списка
        for trip_idx, trip_num in enumerate(trips, start=1):
            print("\n" + "=" * 76)
            print(f" [{trip_idx}/{len(trips)}] ОБРАБОТКА РЕЙСА №{trip_num}")
            print("=" * 76)

            # Переключаемся на основное окно Advantum со списком рейсов
            try:
                driver.switch_to.window(main_handle)
                if hasattr(driver, "bring_window_to_front"):
                    driver.bring_window_to_front()
            except Exception:
                pass

            # Если текущий URL сместился с реестра рейсов — возвращаемся
            if "control/shipments" not in driver.current_url:
                driver.get("https://atms.advantum.ru/#/control/shipments")
                time.sleep(2.5)
                wait_overlays_gone(driver, timeout=8)

            # 6.1. Быстрый поиск рейса (меняем только номер в строке поиска без сброса дат!)
            try:
                advantum.find_and_select_trip(trip_num)
            except Exception as e:
                logger.error("Рейс №%s: ошибка поиска (%s)", trip_num, e)
                summary_data.append({
                    "trip": trip_num,
                    "failed": 0,
                    "updated": 0,
                    "recalc": "—",
                    "status": "Не найден",
                })
                continue

            # 6.2. Чтение списка неотбитых точек доставки ('Не пройдена')
            try:
                failed_points = advantum.get_failed_points()
            except Exception as e:
                logger.error("Рейс №%s: ошибка чтения списка точек (%s)", trip_num, e)
                summary_data.append({
                    "trip": trip_num,
                    "failed": 0,
                    "updated": 0,
                    "recalc": "—",
                    "status": "Ошибка чтения",
                })
                continue

            if not failed_points:
                print(f"\n[Итог] Рейс №{trip_num}: все точки успешно отбиты! Корректировка не требуется.\n")
                summary_data.append({
                    "trip": trip_num,
                    "failed": 0,
                    "updated": 0,
                    "recalc": "—",
                    "status": "Все отбиты",
                })
                continue

            trip_points_updated = 0

            # 6.3. Обработка каждой неотбитой точки рейса
            for p in failed_points:
                print("\n" + "-" * 76)
                print(f" АНАЛИЗ ТОЧКИ №{p.index}: {p.name} (Код: {p.code or 'нет'})")
                print(f" Адрес из Advantum: {p.address}")
                print("-" * 76)

                # Открываем трек водителя в Advantum (00..23 часа), центрируем на точке и считываем координаты
                adv_pos = advantum.open_track_map(point_code=p.code, point_name=p.name)
                adv_lat = adv_pos.get("lat")
                adv_lon = adv_pos.get("lon")

                # Открываем Яндекс Карты в соседней вкладке для визуального контроля
                advantum.open_yandex_maps_tab(p.address)

                # Возвращаем контекст WebDriver на основную вкладку реестра рейсов
                try:
                    driver.switch_to.window(main_handle)
                except Exception:
                    pass

                # Получаем точные эталонные координаты здания через геокодер Яндекс Карт
                try:
                    geo_res = geocoder.geocode(p.address)
                except Exception as e:
                    logger.error("Не удалось геокодировать адрес '%s': %s", p.address, e)
                    continue

                # Сравнение координат системы Advantum и Яндекс Карт
                evaluation = evaluate_coordinates(
                    original_lat=adv_lat,
                    original_lon=adv_lon,
                    target_lat=geo_res.lat,
                    target_lon=geo_res.lon,
                )

                print("\n" + "." * 76)
                print(" РЕЗУЛЬТАТ СРАВНЕНИЯ ЛОКАЦИЙ:")
                print("." * 76)
                if adv_lat and adv_lon:
                    print(f" • Координаты в Advantum (на карте):   Широта: {adv_lat:.8f}, Долгота: {adv_lon:.8f}")
                else:
                    print(f" • Координаты в Advantum:             (отображаются на открытом треке в браузере)")
                print(f" • Реальные координаты (Яндекс Карты):  Широта: {geo_res.lat:.8f}, Долгота: {geo_res.lon:.8f}")
                if evaluation.get("distance_m") is not None:
                    print(f" • Расхождение (дистанция ошибки):      {evaluation['distance_m']} м")
                print(f" • Вердикт системы:                     {evaluation['reason']}")
                print("." * 76)

                # Обновление геоданных в 1С:Предприятие
                if not dry_run:
                    try:
                        success = onec.update_coordinates(
                            code=p.code,
                            address=p.address,
                            lat=geo_res.lat,
                            lon=geo_res.lon,
                            radius=radius,
                            client_name=p.name,
                        )
                    except Exception as e:
                        print(f"\n [1С] ✗ ОШИБКА: {e}\n [1С] Точка '{p.name}' НЕ обновлена.")
                        success = False

                    if success:
                        trip_points_updated += 1
                else:
                    print(" [Dry-run] Запись в 1С пропущена.")

            # 6.4. Пересчет телематики в Advantum для текущего рейса (если были обновления)
            recalc_status = "—"
            if trip_points_updated > 0 and not no_recalc and not dry_run:
                print(f"\n[Advantum] Возврат в окно рейсов и запуск пересчета телематики для рейса №{trip_num}...")
                try:
                    driver.switch_to.window(main_handle)
                    if hasattr(driver, "bring_window_to_front"):
                        driver.bring_window_to_front()
                    time.sleep(1.0)

                    if "control/shipments" not in driver.current_url:
                        driver.get("https://atms.advantum.ru/#/control/shipments")
                        time.sleep(2.5)
                        wait_overlays_gone(driver, timeout=8)
                        advantum.find_and_select_trip(trip_num)
                except Exception as e:
                    logger.debug("Возврат к таблице рейсов: %s", e)

                time.sleep(1.0)
                recalc_ok = advantum.recalculate_telematics(trip_number=trip_num)
                if recalc_ok:
                    recalc_status = "Успешно"
                    print(f" [Advantum] ✓ Пересчет телематики для рейса №{trip_num} успешно запущен!")
                else:
                    recalc_status = "Не сработал"
                    print(f" [Advantum] ⚠ Не удалось нажать кнопку пересчета для рейса №{trip_num}.")

            summary_data.append({
                "trip": trip_num,
                "failed": len(failed_points),
                "updated": trip_points_updated,
                "recalc": recalc_status,
                "status": "Успешно" if trip_points_updated > 0 else ("Проверено" if dry_run else "Без изменений"),
            })

        # 7. Итоговый отчет по всем обработанным рейсам
        total_failed = sum(item["failed"] for item in summary_data)
        total_updated = sum(item["updated"] for item in summary_data)

        print("\n" + "=" * 78)
        print("                 ИТОГОВЫЙ ОТЧЕТ ПАКЕТНОЙ ОБРАБОТКИ РЕЙСОВ")
        print("=" * 78)
        print(f" {'№':<3} | {'Рейс':<12} | {'Неотбитых':<10} | {'Обновлено 1С':<13} | {'Телематика':<12} | {'Статус':<15}")
        print("-" * 78)
        for i, item in enumerate(summary_data, start=1):
            print(f" {i:<3} | {item['trip']:<12} | {item['failed']:<10} | {item['updated']:<13} | {item['recalc']:<12} | {item['status']:<15}")
        print("=" * 78)
        print(f" Обработано рейсов:           {len(trips)}")
        print(f" Всего неотбитых точек:       {total_failed}")
        print(f" Всего обновлено точек в 1С:  {total_updated}")
        print("=" * 78 + "\n")

        if not args.headless:
            input("[Пакетная обработка завершена] Нажмите Enter для закрытия браузера (или закройте вручную)...")

    except KeyboardInterrupt:
        print("\n[Прервано пользователем]")
    except Exception as e:
        logger.exception("Произошла ошибка во время работы: %s", e)
    finally:
        if driver is not None:
            print("[Завершение] Закрытие браузера...")
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()

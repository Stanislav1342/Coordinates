"""
run.py — Главный запускаемый скрипт синхронизации Advantum и 1С:Предприятие.

Использование:
  python run.py --trip 15053328 --date-from 01.10.2026 --date-to 30.10.2026

Параметры:
  --trip           Номер рейса в Advantum (например, 15053328). Обязательный.
  --date-from      Дата начала периода (ДД.ММ.ГГГГ). По умолчанию: 7 дней назад.
  --date-to        Дата окончания периода (ДД.ММ.ГГГГ). По умолчанию: сегодня.
  --radius         Новый радиус зоны в 1С (м), если требуется изменить (например, 300).
  --dry-run        Режим только аудита (без изменения 1С и без пересчета).
  --no-recalc      Не нажимать 'Пересчитать телематику' в Advantum после 1С.
  --headless       Запуск браузера в скрытом режиме (без всплывающего окна).
"""

import argparse
import datetime
import logging
import sys
import time

from advantum_service import AdvantumService
from browser import create_driver, login_to_advantum
from config import load_config
from onec_service import get_onec_service
from yandex_service import YandexGeocoder, evaluate_coordinates

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
        description="Автоматическая проверка и корректировка координат рейса (Advantum -> Яндекс Карты -> 1С)"
    )
    parser.add_argument(
        "--trip",
        type=str,
        required=True,
        help="Номер рейса в Advantum (например, 15053328)",
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

    # 1. Загрузка конфигурации
    config = load_config()
    if args.headless:
        config.headless = True

    print("\n" + "=" * 70)
    print(" АВТОМАТИЗАЦИЯ АУДИТА И КОРРЕКТИРОВКИ КООРДИНАТ (ADVANTUM <-> 1С)")
    print("=" * 70)
    print(f" Рейс:          {args.trip}")
    print(f" Период:        {args.date_from.strftime('%d.%m.%Y')} — {args.date_to.strftime('%d.%m.%Y')}")
    print(f" Режим:         {'[ТОЛЬКО АУДИТ (Dry-run)]' if args.dry_run else '[ПОЛНАЯ СИНХРОНИЗАЦИЯ]'}")
    if args.radius:
        print(f" Радиус зоны:   {args.radius} м")
    print("=" * 70 + "\n")

    # 2. Инициализация сервисов
    geocoder = YandexGeocoder()
    onec = get_onec_service()

    driver = None
    try:
        # 3. Запуск браузера и вход в Advantum
        driver = create_driver(config, headless=config.headless)
        wait = login_to_advantum(driver, config)
        advantum = AdvantumService(driver, wait, config)

        # 4. Переход в раздел 'Рейсы' -> 'Все' с фильтром дат
        advantum.prepare_shipments_page(args.date_from, args.date_to)

        # 5. Поиск и выбор рейса
        advantum.find_and_select_trip(args.trip)

        # 6. Получение неотбитых точек ('Не пройдена')
        failed_points = advantum.get_failed_points()

        if not failed_points:
            print("\n[Итог] Все точки в рейсе успешно отбиты! Корректировка не требуется.\n")
            return

        points_updated_in_1c = 0

        # 7. Обработка каждой проблемной точки
        for p in failed_points:
            print("\n" + "-" * 70)
            print(f" Анализ точки №{p.index}: {p.name} (Код: {p.code or 'нет'})")
            print(f" Адрес из Advantum: {p.address}")
            print("-" * 70)

            # Геокодирование через Яндекс Карты / OSM
            try:
                geo_res = geocoder.geocode(p.address)
                print(f" [Геокодер] Найдено:  {geo_res.found_address}")
                print(f" [Геокодер] Точные координаты: Широта={geo_res.lat:.8f}, Долгота={geo_res.lon:.8f}")
            except Exception as e:
                logger.error("Не удалось геокодировать адрес '%s': %s", p.address, e)
                continue

            # Если мы в режиме применения изменений (или эмуляции)
            if not args.dry_run:
                # Обновляем координаты в 1С
                success = onec.update_coordinates(
                    code=p.code,
                    address=p.address,
                    lat=geo_res.lat,
                    lon=geo_res.lon,
                    radius=args.radius,
                    client_name=p.name,
                )
                if success:
                    points_updated_in_1c += 1
            else:
                print(" [Dry-run] Запись в 1С пропущена.")

        # 8. Пересчет телематики в Advantum
        if points_updated_in_1c > 0 and not args.no_recalc and not args.dry_run:
            print("\n[Advantum] Точки обновлены в 1С. Запуск пересчета телематики в Advantum...")
            time.sleep(2)  # пауза перед пересчетом
            recalc_ok = advantum.recalculate_telematics()
            if recalc_ok:
                print(" [Advantum] ✓ Пересчет телематики успешно запрошен!")
            else:
                print(" [Advantum] ⚠ Не удалось нажать кнопку пересчета телематики.")

        print("\n" + "=" * 70)
        print(" ОБРАБОТКА РЕЙСА ЗАВЕРШЕНА УСПЕШНО")
        print(f" Всего неотбитых точек: {len(failed_points)}")
        print(f" Обновлено в 1С:         {points_updated_in_1c}")
        print("=" * 70 + "\n")

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

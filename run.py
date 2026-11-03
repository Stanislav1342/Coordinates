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
            print("\n" + "=" * 70)
            print(f" АНАЛИЗ ТОЧКИ №{p.index}: {p.name} (Код: {p.code or 'нет'})")
            print(f" Адрес из Advantum: {p.address}")
            print("=" * 70)

            # 7.1. Открываем трек водителя в Advantum (00..23 часа), центрируем на точке и считываем координаты
            adv_pos = advantum.open_track_map(point_code=p.code, point_name=p.name)
            adv_lat = adv_pos.get("lat")
            adv_lon = adv_pos.get("lon")

            # 7.2. Открываем Яндекс Карты в соседней вкладке браузера для визуальной сверки
            advantum.open_yandex_maps_tab(p.address)

            # 7.3. Получаем точные эталонные координаты здания через Яндекс Карты
            try:
                geo_res = geocoder.geocode(p.address)
            except Exception as e:
                logger.error("Не удалось геокодировать адрес '%s': %s", p.address, e)
                continue

            # 7.4. Сравнение положения точки в Advantum и в Яндекс Картах
            evaluation = evaluate_coordinates(
                original_lat=adv_lat,
                original_lon=adv_lon,
                target_lat=geo_res.lat,
                target_lon=geo_res.lon,
            )

            print("\n" + "-" * 70)
            print(" РЕЗУЛЬТАТ СРАВНЕНИЯ ЛОКАЦИЙ:")
            print("-" * 70)
            if adv_lat and adv_lon:
                print(f" • Координаты в Advantum (на карте):   Широта: {adv_lat:.8f}, Долгота: {adv_lon:.8f}")
            else:
                print(f" • Координаты в Advantum:             (отображаются на открытом треке в браузере)")
            print(f" • Реальные координаты (Яндекс Карты):  Широта: {geo_res.lat:.8f}, Долгота: {geo_res.lon:.8f}")
            if evaluation.get("distance_m") is not None:
                print(f" • Расхождение (дистанция ошибки):      {evaluation['distance_m']} м")
            print(f" • Вердикт системы:                     {evaluation['reason']}")
            print("-" * 70)

            # 7.5. Интерактивная пауза для визуального контроля
            if not args.headless:
                print("\n[Визуальный контроль] В браузере открыты: 1) вкладка с треком Advantum, 2) вкладка с Яндекс Картами.")
                input(">>> Проверьте визуально локацию на экране и нажмите Enter для перехода в 1С и обновления...")

            # 7.6. Если мы в режиме применения изменений
            if not args.dry_run:
                # Переключаемся на окно 1С и обновляем координаты
                try:
                    success = onec.update_coordinates(
                        code=p.code,
                        address=p.address,
                        lat=geo_res.lat,
                        lon=geo_res.lon,
                        radius=args.radius,
                        client_name=p.name,
                    )
                except Exception as e:
                    print(f"\n [1С] ✗ ОШИБКА: {e}\n [1С] Точка '{p.name}' НЕ обновлена.")
                    success = False
                if success:
                    points_updated_in_1c += 1
            else:
                print(" [Dry-run] Запись в 1С пропущена.")

        # 8. Пересчет телематики в Advantum
        if points_updated_in_1c > 0 and not args.no_recalc and not args.dry_run:
            print("\n[Advantum] Возврат в окно рейсов и запуск пересчета телематики...")
            try:
                # 1. Переключаемся на основную вкладку с Advantum
                driver.switch_to.window(driver.window_handles[0])
                time.sleep(1)

                # 2. Если открыта страница трека /map — возвращаемся к таблице рейсов
                if "control/shipments" not in driver.current_url:
                    print("[Advantum] Возврат из карты трека в таблицу рейсов...")
                    driver.get("https://atms.advantum.ru/#/control/shipments")
                    time.sleep(3)
                    wait_overlays_gone(driver, timeout=10)
                    # Выбираем рейс снова, чтобы открылась панель инструментов
                    advantum.find_and_select_trip(args.trip)
                else:
                    # Закрываем модальное окно трека, если оно открыто поверх таблицы
                    close_btns = driver.find_elements(
                        By.XPATH,
                        "//div[contains(@class, 'map')]//button[contains(@class, 'close')] | //button[@aria-label='Close']",
                    )
                    for cb in close_btns:
                        if cb.is_displayed():
                            driver.execute_script("arguments[0].click();", cb)
                            time.sleep(1)
                            break
            except Exception as e:
                logger.debug("Возврат к таблице рейсов: %s", e)

            time.sleep(1.5)
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

        if not args.headless:
            input("[Процесс завершен] Нажмите Enter для закрытия браузера (или закройте вручную)...")

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

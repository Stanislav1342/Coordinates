"""
advantum_service.py — Сервис взаимодействия с веб-интерфейсом Advantum.

Реализует:
1. Вход в Advantum и переход в раздел 'Рейсы' -> 'Все'.
2. Установку фильтра по датам (до 30 дней).
3. Поиск рейса по номеру.
4. Выбор строки рейса и парсинг таблицы 'Точки доставки'.
5. Извлечение неотбитых точек (со статусом 'Не пройдена').
6. Нажатие кнопки 'Пересчитать телематику' с подтверждением.
"""

import datetime
import logging
import re
import time
from dataclasses import dataclass
from typing import List, Tuple

from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import Config
from utils import wait_overlays_gone, stable_click

logger = logging.getLogger(__name__)


RUSSIAN_MONTHS = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
    "май": 5, "июнь": 6, "июль": 7, "август": 8,
    "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}


def _parse_month_header(text: str) -> Tuple[int, int]:
    """Парсит заголовок месяца вида 'Октябрь 2026' в (year, month)."""
    parts = text.strip().split()
    if len(parts) >= 2:
        m_name = parts[0].lower()
        y_num = int(parts[1])
        m_num = RUSSIAN_MONTHS.get(m_name)
        if m_num:
            return y_num, m_num
    raise ValueError(f"Не удалось распознать заголовок месяца: '{text}'")


@dataclass
class DeliveryPoint:
    index: str
    status: str
    name: str
    code: str
    address: str
    operation: str
    plan_arrival: str = ""
    is_failed: bool = False


class AdvantumService:
    """Сервис для работы с рейсами и телематикой в Advantum."""

    def __init__(self, driver, wait: WebDriverWait, config: Config):
        self.driver = driver
        self.wait = wait
        self.config = config

    def prepare_shipments_page(
        self,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> None:
        """
        Переходит в раздел 'Рейсы' -> 'Все' и применяет фильтр дат.
        """
        print("[Advantum] Переход в раздел 'Рейсы'...")
        current_url = self.driver.current_url
        if "control/shipments" not in current_url:
            self.driver.get("https://atms.advantum.ru/#/control/shipments")
            time.sleep(3)

        wait_overlays_gone(self.driver, timeout=10)

        # 1. Клик по вкладке 'Рейсы'
        try:
            reisy_btn = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//span[text()='Рейсы'] | //div[contains(text(), 'Рейсы')]")
                )
            )
            self.driver.execute_script("arguments[0].click();", reisy_btn)
            time.sleep(1.5)
        except Exception:
            pass

        # 2. Клик по вкладке 'Все'
        try:
            vse_btn = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//*[text()='Все']"))
            )
            self.driver.execute_script("arguments[0].click();", vse_btn)
            time.sleep(1.5)
        except Exception:
            pass

        wait_overlays_gone(self.driver, timeout=8)

        # 3. Фильтр дат
        self._apply_date_filter(date_from, date_to)
        print("[Advantum] Раздел 'Рейсы' готов к поиску.")

    def _apply_date_filter(
        self, start_date: datetime.date, end_date: datetime.date
    ) -> bool:
        """Устанавливает диапазон дат в фильтре Advantum с перемоткой месяцев."""
        # 1. Проверяем, развернута ли панель фильтров
        filter_fields = self.driver.find_elements(
            By.XPATH, "//div[contains(@class, 'MuiPickersTextField-root')]"
        )
        if not filter_fields or not filter_fields[0].is_displayed():
            try:
                expand_btn = self.wait.until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//div[contains(@class, 'extended-grid__grid-filter-expand-button')]",
                        )
                    )
                )
                self.driver.execute_script("arguments[0].click();", expand_btn)
                time.sleep(1.5)
            except Exception:
                pass

        # 2. Проверяем текущее значение
        try:
            period_input = self.driver.find_element(
                By.XPATH, "//div[contains(@class, 'MuiPickersTextField-root')]//input"
            )
            cur_val = period_input.get_attribute("value") or ""
            start_str = start_date.strftime("%d.%m.%y")
            end_str = end_date.strftime("%d.%m.%y")
            if start_str in cur_val and end_str in cur_val:
                print(f"[Advantum] Период уже установлен: {cur_val}")
                return True
        except Exception:
            pass

        print(f"[Advantum] Открытие календаря для периода: {start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}...")
        cal_btn = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//div[contains(@class, 'MuiPickersTextField-root')]//button")
            )
        )
        self.driver.execute_script("arguments[0].click();", cal_btn)
        time.sleep(1.5)

        # 3. Ожидаем появления календаря и считываем отображаемый месяц
        self.wait.until(
            EC.presence_of_all_elements_located(
                (By.XPATH, "//div[contains(@class, 'MuiDateRangeCalendar-monthContainer')]")
            )
        )

        left_lbl = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.XPATH,
                    "//div[contains(@class, 'MuiDateRangeCalendar-monthContainer')][1]//span[contains(@class, 'MuiTypography-subtitle1')]",
                )
            )
        ).text
        cur_year, cur_month = _parse_month_header(left_lbl)
        month_delta = (start_date.year - cur_year) * 12 + (start_date.month - cur_month)
        print(f"[Advantum] Календарь открыт на: {left_lbl} ({cur_month}.{cur_year}), целевой месяц: {start_date.month}.{start_date.year}, сдвиг: {month_delta}")

        # Переключаем назад, если целевой месяц раньше текущего
        if month_delta < 0:
            for _ in range(abs(month_delta)):
                prev_btn = self.wait.until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//div[contains(@class, 'MuiDateRangeCalendar-monthContainer')][1]//button[contains(@class, 'MuiPickersArrowSwitcher-previousIconButton')]",
                        )
                    )
                )
                self.driver.execute_script("arguments[0].click();", prev_btn)
                time.sleep(0.3)
        # Переключаем вперед, если целевой месяц позже текущего
        elif month_delta > 0:
            for _ in range(month_delta):
                next_btn = self.wait.until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//div[contains(@class, 'MuiDateRangeCalendar-monthContainer')][2]//button[contains(@class, 'MuiPickersArrowSwitcher-nextIconButton')]",
                        )
                    )
                )
                self.driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(0.3)

        time.sleep(0.5)

        # 4. Кликаем день даты начала в Container 1 (левый контейнер)
        start_day_xpath = (
            f"//div[contains(@class, 'MuiDateRangeCalendar-monthContainer')][1]"
            f"//button[@role='gridcell' and normalize-space(text())='{start_date.day}']"
        )
        start_day_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, start_day_xpath)))
        self.driver.execute_script("arguments[0].click();", start_day_btn)
        time.sleep(0.4)

        # 5. Кликаем день даты окончания
        end_delta = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
        if end_delta == 0:
            # Тот же месяц — Container 1
            end_day_xpath = (
                f"//div[contains(@class, 'MuiDateRangeCalendar-monthContainer')][1]"
                f"//button[@role='gridcell' and normalize-space(text())='{end_date.day}']"
            )
            end_day_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, end_day_xpath)))
            self.driver.execute_script("arguments[0].click();", end_day_btn)
        elif end_delta == 1:
            # Следующий месяц — Container 2 (он открыт справа)
            end_day_xpath = (
                f"//div[contains(@class, 'MuiDateRangeCalendar-monthContainer')][2]"
                f"//button[@role='gridcell' and normalize-space(text())='{end_date.day}']"
            )
            end_day_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, end_day_xpath)))
            self.driver.execute_script("arguments[0].click();", end_day_btn)
        else:
            # Более одного месяца вперед — доматываем правый контейнер
            for _ in range(end_delta - 1):
                next_btn = self.wait.until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//div[contains(@class, 'MuiDateRangeCalendar-monthContainer')][2]//button[contains(@class, 'MuiPickersArrowSwitcher-nextIconButton')]",
                        )
                    )
                )
                self.driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(0.3)
            time.sleep(0.4)
            end_day_xpath = (
                f"//div[contains(@class, 'MuiDateRangeCalendar-monthContainer')][2]"
                f"//button[@role='gridcell' and normalize-space(text())='{end_date.day}']"
            )
            end_day_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, end_day_xpath)))
            self.driver.execute_script("arguments[0].click();", end_day_btn)

        time.sleep(0.5)

        # 6. Кнопка 'Применить'
        print("[Advantum] Нажатие 'Применить' в календаре...")
        apply_btn = self.wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(@class, 'MuiButton-root') and contains(text(), 'Применить')]",
                )
            )
        )
        self.driver.execute_script("arguments[0].click();", apply_btn)
        time.sleep(2)
        wait_overlays_gone(self.driver, timeout=10)

        try:
            new_val = self.driver.find_element(
                By.XPATH, "//div[contains(@class, 'MuiPickersTextField-root')]//input"
            ).get_attribute("value")
            print(f"[Advantum] Установлен период: {new_val}")
        except Exception:
            pass

        return True

    def find_and_select_trip(self, trip_number: str) -> bool:
        """
        Ищет рейс по номеру в строке поиска и выбирает его строку в таблице.
        """
        print(f"[Advantum] Поиск рейса №{trip_number}...")
        wait_overlays_gone(self.driver, timeout=6)

        search_input = self.wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[contains(@class, 'extended-grid__grid-filter-search')]//input")
            )
        )

        # Очистка поиска
        try:
            clear_btn = self.driver.find_elements(
                By.XPATH, "//div[contains(@class, 'search-field__clear')]//button"
            )
            if clear_btn and clear_btn[0].is_displayed():
                self.driver.execute_script("arguments[0].click();", clear_btn[0])
                time.sleep(0.5)
            else:
                search_input.send_keys(Keys.COMMAND + "a" if "darwin" in self.driver.capabilities.get("platformName", "").lower() else Keys.CONTROL + "a")
                search_input.send_keys(Keys.BACKSPACE)
        except Exception:
            pass

        # Ввод номера рейса
        search_input.click()
        search_input.send_keys(str(trip_number))
        search_input.send_keys(Keys.ENTER)
        time.sleep(3)
        wait_overlays_gone(self.driver, timeout=10)

        # Кликаем строку найденного рейса
        row_xpath = f"//div[@role='row' and contains(., '{trip_number}')]"
        try:
            row_elem = self.wait.until(EC.element_to_be_clickable((By.XPATH, row_xpath)))
            self.driver.execute_script("arguments[0].click();", row_elem)
            time.sleep(2)
            print(f"[Advantum] Рейс {trip_number} выбран.")
            return True
        except Exception as e:
            logger.error("Не удалось выбрать строку рейса: %s", e)
            raise ValueError(f"Рейс №{trip_number} не найден в таблице!")

    def parse_delivery_points(self) -> List[DeliveryPoint]:
        """
        Парсит панель 'Точки доставки' внизу экрана.
        Возвращает список всех точек рейса.
        """
        print("[Advantum] Чтение панели 'Точки доставки'...")
        wait_overlays_gone(self.driver, timeout=5)
        time.sleep(1.5)

        # Ожидаем появления таблицы 'Точки доставки'
        points_table = self.wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[contains(., 'Точки доставки')]//div[@role='grid' or contains(@class, 'extended-grid')]")
            )
        )

        rows = self.driver.find_elements(
            By.XPATH,
            "//div[contains(., 'Точки доставки')]//div[@role='row'][not(contains(@class, 'header')) and not(contains(@class, 'head'))]"
        )

        parsed_points = []
        for r in rows:
            text = r.text.strip()
            if not text:
                continue

            # Определяем статус
            is_failed = "Не пройдена" in text
            status = "Не пройдена" if is_failed else "Пройдена / В окне"
            if "Попадание в окно" in text:
                status = "Попадание в окно"

            # Извлекаем код МСК...
            code_match = re.search(r"(МСК\d+)", text)
            code = code_match.group(1) if code_match else ""

            # Извлекаем номер по порядку
            num_match = re.search(r"^\s*(\d+)", text)
            idx = num_match.group(1) if num_match else "1"

            # Извлекаем название и адрес из колонок
            cells = r.find_elements(By.XPATH, ".//div[@role='gridcell' or contains(@class, 'cell')]")
            raw_cells = [c.text.strip() for c in cells if c.text.strip()]

            # Название клиента (чистим от номеров строк и статусов)
            name = ""
            for line in text.splitlines():
                line = line.strip()
                if "МСК" in line:
                    m = re.search(r"^([^\(]+?)\s*\(МСК\d+\)", line)
                    if m:
                        name = m.group(1).strip()
                        break
            if not name:
                name_match = re.search(r"([А-Яа-яA-Za-z0-9\- ]+?)\s*\(МСК\d+\)", text)
                if name_match:
                    name = name_match.group(1).strip()
                elif len(raw_cells) >= 3:
                    name = raw_cells[2]

            # Адрес точки
            address = ""
            addr_match = re.search(r"(?:Московская|г\.|обл|д\.|территория|ул\.)[^\n\r]+", text)
            if addr_match:
                address = addr_match.group(0).strip()
            elif len(raw_cells) >= 4:
                address = raw_cells[3]

            point = DeliveryPoint(
                index=idx,
                status=status,
                name=name,
                code=code,
                address=address,
                operation="Погрузка" if "Погрузка" in text else "Разгрузка",
                is_failed=is_failed,
            )
            parsed_points.append(point)

        print(f"[Advantum] Найдено точек доставки: {len(parsed_points)}")
        return parsed_points

    def get_failed_points(self) -> List[DeliveryPoint]:
        """Возвращает только неотбитые точки со статусом 'Не пройдена'."""
        all_points = self.parse_delivery_points()
        failed = [p for p in all_points if p.is_failed]
        print(f"[Advantum] Неотбитых точек ('Не пройдена'): {len(failed)}")
        for p in failed:
            print(f"  • Точка №{p.index} [{p.code}]: {p.name} | {p.address}")
        return failed

    def open_track_map(self, point_code: str = "") -> dict:
        """
        Нажимает кнопку 'На карте' для выбранного рейса,
        устанавливает фильтр времени (00:xx до 23:xx), обновляет трек
        и центрирует карту на проблемной точке.
        Возвращает текущие координаты точки из Advantum, если удалось прочитать.
        """
        print("[Advantum] Открытие трека водителя ('На карте')...")
        wait_overlays_gone(self.driver, timeout=5)

        map_btn_xpath = (
            "//button[@title='На карте' or @aria-label='На карте']"
            " | //div[contains(@class, 'toolbar')]//button[1]"
            " | //button[contains(@class, 'MuiButton') and .//*[contains(@title, 'На карте')]]"
        )
        try:
            map_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, map_btn_xpath)))
            self.driver.execute_script("arguments[0].click();", map_btn)
            time.sleep(3)
        except Exception as e:
            logger.warning("Не удалось кликнуть 'На карте': %s", e)
            return {}

        # Ожидаем открытия модального окна карты / трека
        try:
            self.wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[contains(@class, 'leaflet') or contains(@class, 'map')] | //input[contains(@value, ':')]")
                )
            )
            print("[Advantum] Окно трека открыто.")
            time.sleep(2)

            # Находим поля ввода времени: 'Начало трека' и 'Окончание трека'
            time_inputs = self.driver.find_elements(
                By.XPATH, "//div[contains(@class, 'map') or contains(@class, 'track') or contains(@class, 'panel')]//input[contains(@value, ':')]"
            )
            if not time_inputs:
                time_inputs = self.driver.find_elements(By.XPATH, "//input[contains(@value, ':')]")

            if len(time_inputs) >= 2:
                # 1. Начало трека -> устанавливаем 00 часов
                try:
                    print("[Advantum] Установка начала трека на 00:xx...")
                    # Кликаем иконку календаря первого поля
                    parent_box = time_inputs[0].find_element(By.XPATH, "./..")
                    cal_btns = parent_box.find_elements(By.XPATH, ".//button")
                    if cal_btns:
                        self.driver.execute_script("arguments[0].click();", cal_btns[0])
                    else:
                        time_inputs[0].click()
                    time.sleep(1.2)

                    # В открывшемся попапе выбираем 00
                    h00 = self.driver.find_elements(By.XPATH, "//li[normalize-space(text())='00'] | //button[normalize-space(text())='00']")
                    if h00:
                        self.driver.execute_script("arguments[0].click();", h00[0])
                        time.sleep(0.5)

                    # Нажимаем OK
                    ok_btn = self.driver.find_elements(By.XPATH, "//button[normalize-space(text())='OK']")
                    if ok_btn:
                        self.driver.execute_script("arguments[0].click();", ok_btn[0])
                    time.sleep(0.5)
                except Exception as e:
                    logger.debug("Настройка начала трека: %s", e)

                # 2. Окончание трека -> устанавливаем 23 часа
                try:
                    print("[Advantum] Установка окончания трека на 23:xx...")
                    parent_box = time_inputs[1].find_element(By.XPATH, "./..")
                    cal_btns = parent_box.find_elements(By.XPATH, ".//button")
                    if cal_btns:
                        self.driver.execute_script("arguments[0].click();", cal_btns[0])
                    else:
                        time_inputs[1].click()
                    time.sleep(1.2)

                    h23 = self.driver.find_elements(By.XPATH, "//li[normalize-space(text())='23'] | //button[normalize-space(text())='23']")
                    if h23:
                        self.driver.execute_script("arguments[0].click();", h23[0])
                        time.sleep(0.5)

                    ok_btn = self.driver.find_elements(By.XPATH, "//button[normalize-space(text())='OK']")
                    if ok_btn:
                        self.driver.execute_script("arguments[0].click();", ok_btn[0])
                    time.sleep(0.5)
                except Exception as e:
                    logger.debug("Настройка окончания трека: %s", e)

            # 3. Нажимаем круглую синюю кнопку обновления трека [R]
            try:
                print("[Advantum] Нажатие кнопки обновления трека...")
                refresh_btns = self.driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class, 'map') or contains(@class, 'track')]//button[contains(@class, 'MuiButton-root') and .//*[name()='svg']]"
                    " | //button[contains(@class, 'refresh')]"
                )
                for rb in refresh_btns:
                    if rb.is_displayed():
                        self.driver.execute_script("arguments[0].click();", rb)
                        break
                time.sleep(3)
            except Exception as e:
                logger.debug("Кнопка обновления трека: %s", e)

            # 4. В списке точек справа нажимаем на проблемную точку (например, БИОКОДЕ / МСК000132723)
            if point_code:
                try:
                    print(f"[Advantum] Центрирование карты на точке [{point_code}]...")
                    point_card = self.driver.find_elements(
                        By.XPATH,
                        f"//div[contains(., '{point_code}') and (contains(@class, 'point') or contains(@class, 'item') or @role='row' or contains(@class, 'card'))]"
                    )
                    if point_card:
                        self.driver.execute_script("arguments[0].click();", point_card[-1])
                        time.sleep(2)
                except Exception as e:
                    logger.debug("Клик по точке в списке карты: %s", e)

            # 5. Считываем координаты центра карты (где установлена точка в Advantum)
            adv_coords = None
            try:
                adv_coords = self.driver.execute_script("""
                    var c = document.querySelector('.leaflet-container');
                    if (c) {
                        for (var k in c) {
                            if (k.indexOf('leaflet') !== -1 && c[k] && c[k].getCenter) {
                                var center = c[k].getCenter();
                                return {lat: center.lat, lon: center.lng};
                            }
                        }
                    }
                    return null;
                """)
            except Exception:
                pass

            return adv_coords or {}

        except Exception as e:
            logger.warning("Ошибка при работе с окном трека: %s", e)
            return {}

    def open_yandex_maps_tab(self, address: str) -> None:
        """Открывает Яндекс Карты с адресом в новой вкладке браузера."""
        print(f"[Яндекс Карты] Открытие адреса в новой вкладке: {address}...")
        try:
            js = "window.open('https://yandex.ru/maps/?text=' + encodeURIComponent(arguments[0]), '_blank');"
            self.driver.execute_script(js, address)
            time.sleep(1.5)
        except Exception as e:
            logger.warning("Не удалось открыть вкладку Яндекс Карт: %s", e)

    def recalculate_telematics(self) -> bool:
        """
        Нажимает кнопку 'Пересчитать телематику' на панели инструментов рейса
        и подтверждает действие в модальном окне.
        """
        print("[Advantum] Запуск пересчета телематики...")
        wait_overlays_gone(self.driver, timeout=6)

        # 1. Поиск кнопки с тултипом 'Пересчитать телематику'
        recalc_btn_xpath = (
            "//button[@title='Пересчитать телематику' or @aria-label='Пересчитать телематику']"
            " | //button[contains(@class, 'MuiButton') and .//*[contains(@title, 'Пересчитать телематику')]]"
            " | //div[contains(@class, 'toolbar')]//button[3]"
        )

        try:
            recalc_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, recalc_btn_xpath)))
            self.driver.execute_script("arguments[0].click();", recalc_btn)
            time.sleep(1.5)
            print("[Advantum] Нажата кнопка 'Пересчитать телематику'.")
        except Exception as e:
            logger.error("Кнопка 'Пересчитать телематику' не найдена: %s", e)
            return False

        # 2. Модальное окно подтверждения 'Пересчитать телематику?' -> кнопка 'Да'
        try:
            confirm_modal = self.wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[@role='dialog' or contains(@class, 'MuiDialog-paper')]")
                )
            )
            yes_btn = confirm_modal.find_element(
                By.XPATH, ".//button[normalize-space(text())='Да']"
            )
            self.driver.execute_script("arguments[0].click();", yes_btn)
            time.sleep(2)
            wait_overlays_gone(self.driver, timeout=10)
            print("[Advantum] Подтверждение пересчета телематики ('Да') успешно отправлено!")
            return True
        except Exception as e:
            logger.error("Не удалось подтвердить модальное окно пересчета: %s", e)
            return False

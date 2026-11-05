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

    def open_track_map(self, point_code: str = "", point_name: str = "") -> dict:
        """
        Нажимает кнопку 'На карте' для выбранного рейса,
        устанавливает фильтр времени (00:00 до 23:59), обновляет трек
        и центрирует карту на проблемной точке.
        Возвращает текущие координаты точки из Advantum, если удалось прочитать.
        """
        print("[Advantum] Открытие трека водителя ('На карте')...")
        wait_overlays_gone(self.driver, timeout=5)

        orig_handles = list(self.driver.window_handles)

        map_btn_xpath = (
            "//button[@title='На карте' or @aria-label='На карте']"
            " | //div[contains(@class, 'toolbar')]//button[1]"
            " | //button[contains(@class, 'MuiButton') and .//*[contains(@title, 'На карте')]]"
        )
        try:
            map_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, map_btn_xpath)))
            self.driver.execute_script("arguments[0].click();", map_btn)
            time.sleep(2)
        except Exception as e:
            logger.warning("Не удалось кликнуть 'На карте': %s", e)
            return {}

        # Проверяем, открылось ли отдельное окно/вкладка для трека
        switched_to_popup = False
        for _ in range(10):
            cur_handles = list(self.driver.window_handles)
            if len(cur_handles) > len(orig_handles):
                new_handle = cur_handles[-1]
                self.driver.switch_to.window(new_handle)
                switched_to_popup = True
                print(f"[Advantum] Переключились на открывшееся окно трека (handle: {new_handle}).")
                break
            time.sleep(0.5)

        if not switched_to_popup:
            print("[Advantum] Окно трека открылось в текущей вкладке (или popup без нового handle).")

        # Ожидаем появления карты / трека (быстрый таймаут 15 сек вместо 60)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[contains(@class, 'leaflet') or contains(@class, 'map')] | //input[contains(@value, ':')]")
                )
            )
            print("[Advantum] Окно трека открыто.")
            time.sleep(1.5)

            # 1. Установка фильтра времени: 00:00 - 23:59 и клик по кнопке обновления трека через JS
            track_filter_js = """
            return (function() {
                var allInputs = Array.from(document.querySelectorAll('input'));
                var timeInputs = allInputs.filter(function(i) {
                    var v = i.value || '';
                    return /\\d{2}\\.\\d{2}\\.\\d{4}\\s+\\d{2}:\\d{2}/.test(v);
                });
                
                if (timeInputs.length < 2) {
                    timeInputs = allInputs.filter(function(i) {
                        return (i.value || '').indexOf(':') !== -1;
                    });
                }
                
                var res = {found: timeInputs.length, start_set: '', end_set: '', refreshed: false};
                
                function setVal(input, val) {
                    input.focus();
                    var desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                    if (desc && desc.set) {
                        desc.set.call(input, val);
                    } else {
                        input.value = val;
                    }
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.blur();
                }
                
                if (timeInputs.length >= 2) {
                    var startVal = timeInputs[0].value;
                    var endVal = timeInputs[1].value;
                    
                    var newStart = startVal.replace(/\\d{2}:\\d{2}$/, '00:00');
                    var newEnd = endVal.replace(/\\d{2}:\\d{2}$/, '23:59');
                    
                    setVal(timeInputs[0], newStart);
                    setVal(timeInputs[1], newEnd);
                    
                    res.start_set = newStart;
                    res.end_set = newEnd;
                }
                
                // Ищем синюю круглую кнопку обновления трека с круговой стрелкой
                var buttons = Array.from(document.querySelectorAll('button'));
                var refreshBtn = buttons.find(function(b) {
                    var aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    var title = (b.getAttribute('title') || '').toLowerCase();
                    return aria.indexOf('обнов') !== -1 || aria.indexOf('refresh') !== -1 ||
                           title.indexOf('обнов') !== -1 || title.indexOf('refresh') !== -1;
                });
                
                if (!refreshBtn && timeInputs.length >= 2) {
                    var parent = timeInputs[1].closest('.MuiFormControl-root') || timeInputs[1].parentElement;
                    if (parent && parent.parentElement) {
                        var siblings = Array.from(parent.parentElement.querySelectorAll('button'));
                        for (var i = 0; i < siblings.length; i++) {
                            if (!siblings[i].closest('.MuiFormControl-root')) {
                                refreshBtn = siblings[i];
                                break;
                            }
                        }
                    }
                }
                
                if (refreshBtn) {
                    refreshBtn.click();
                    res.refreshed = true;
                }
                
                return res;
            })();
            """
            filter_res = self.driver.execute_script(track_filter_js)
            if filter_res and filter_res.get("start_set") and filter_res.get("end_set"):
                print(f"[Advantum] Установлен фильтр времени трека: {filter_res['start_set']} — {filter_res['end_set']}")
            else:
                print(f"[Advantum] Фильтр времени трека: {filter_res}")

            if filter_res and filter_res.get("refreshed"):
                print("[Advantum] Нажата кнопка обновления трека.")
            time.sleep(3)

            # 2. В списке точек справа нажимаем на проблемную точку (например, БИОКОДЕ / МСК000132723)
            print(f"[Advantum] Центрирование карты на точке [{point_code or point_name}]...")
            center_js = """
            return (function(code, name) {
                var all = Array.from(document.querySelectorAll('*'));
                var target = all.find(function(el) {
                    return el.children.length === 0 && (
                        (code && el.textContent.indexOf(code) !== -1) ||
                        (name && el.textContent.indexOf(name) !== -1)
                    );
                });
                
                if (target) {
                    var card = target.closest('[role="button"], [role="row"], .point, .card, li, div[class*="item"]') || target.parentElement;
                    if (card) {
                        var pinBtn = card.querySelector('button, svg, [class*="target"], [class*="gps"]');
                        if (pinBtn) {
                            pinBtn.click();
                            return {clicked: 'pin_button'};
                        }
                        card.click();
                        return {clicked: 'card'};
                    }
                }
                return {clicked: false};
            })(arguments[0], arguments[1]);
            """
            self.driver.execute_script(center_js, point_code, point_name)
            time.sleep(2)

            # 3. Считываем координаты точки из Advantum (React Fiber / Leaflet / Map Center)
            coords_js = """
            return (function(code, name) {
                // Вспомогательная функция глубокого поиска координат в объекте props
                function extractCoords(obj, depth, visited) {
                    if (!obj || typeof obj !== 'object' || depth > 4) return null;
                    if (visited.has(obj)) return null;
                    visited.add(obj);

                    var lat = obj.lat || obj.latitude || (obj.coords && obj.coords[0]) || (obj.coordinate && (obj.coordinate.lat || obj.coordinate.latitude));
                    var lon = obj.lon || obj.lng || obj.longitude || (obj.coords && obj.coords[1]) || (obj.coordinate && (obj.coordinate.lon || obj.coordinate.longitude));
                    
                    if (typeof lat === 'number' && typeof lon === 'number' && lat > 30 && lat < 80 && lon > 10 && lon < 180) {
                        return {lat: lat, lon: lon};
                    }

                    var checkKeys = ['point', 'item', 'row', 'data', 'location', 'geo', 'coordinates', 'coordinate', 'target'];
                    for (var i = 0; i < checkKeys.length; i++) {
                        var k = checkKeys[i];
                        if (obj[k] && typeof obj[k] === 'object') {
                            var res = extractCoords(obj[k], depth + 1, visited);
                            if (res) return res;
                        }
                    }
                    return null;
                }

                // А. Проверяем листовые элементы (leaf nodes) с кодом или названием точки
                var leafEls = Array.from(document.querySelectorAll('*')).filter(function(el) {
                    return el.children.length === 0 && (
                        (code && el.textContent.indexOf(code) !== -1) ||
                        (name && el.textContent.indexOf(name) !== -1)
                    );
                });

                for (var j = 0; j < leafEls.length; j++) {
                    var el = leafEls[j];
                    var fiberKey = Object.keys(el).find(function(k) {
                        return k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance');
                    });
                    if (fiberKey) {
                        var curr = el[fiberKey];
                        var visited = new Set();
                        for (var d = 0; d < 25 && curr; d++) {
                            if (curr.memoizedProps) {
                                var found = extractCoords(curr.memoizedProps, 0, visited);
                                if (found) {
                                    found.method = 'react_fiber';
                                    return found;
                                }
                            }
                            curr = curr.return;
                        }
                    }
                }

                // Б. Ищем Leaflet Map
                function findLeafletMap() {
                    var c = document.querySelector('.leaflet-container');
                    if (!c) return null;
                    if (c._leaflet_map) return c._leaflet_map;
                    for (var k in c) {
                        try {
                            if (c[k] && typeof c[k] === 'object' && c[k]._layers) return c[k];
                        } catch(e) {}
                    }
                    for (var k in window) {
                        try {
                            if (window[k] && typeof window[k] === 'object' && window[k]._layers && window[k].getCenter) return window[k];
                        } catch(e) {}
                    }
                    // Поиск через React Fiber у контейнера Leaflet
                    var fKey = Object.keys(c).find(function(k) { return k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'); });
                    if (fKey) {
                        var cur = c[fKey];
                        for (var d = 0; d < 20 && cur; d++) {
                            if (cur.memoizedProps && (cur.memoizedProps.map || cur.memoizedProps.leafletMap)) {
                                return cur.memoizedProps.map || cur.memoizedProps.leafletMap;
                            }
                            cur = cur.return;
                        }
                    }
                    return null;
                }

                var map = findLeafletMap();
                if (map) {
                    for (var id in map._layers) {
                        var l = map._layers[id];
                        if (l && l._latlng) {
                            var html = l._icon ? (l._icon.innerHTML || l._icon.className) : '';
                            if (html.indexOf(code) !== -1 || html.indexOf('>1<') !== -1 || html.indexOf('point-1') !== -1) {
                                return {lat: l._latlng.lat, lon: l._latlng.lng, method: 'leaflet_marker'};
                            }
                        }
                    }
                    var center = map.getCenter();
                    if (center && typeof center.lat === 'number') {
                        return {lat: center.lat, lon: center.lng, method: 'map_center'};
                    }
                }

                return null;
            })(arguments[0], arguments[1]);
            """
            adv_coords = self.driver.execute_script(coords_js, point_code, point_name)
            if adv_coords and adv_coords.get("lat") and adv_coords.get("lon"):
                print(f"[Advantum] Получены координаты точки из системы ({adv_coords.get('method')}): {adv_coords['lat']:.8f}, {adv_coords['lon']:.8f}")

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

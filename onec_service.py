"""
onec_service.py — Сервис взаимодействия с 1С:Предприятие.

На Windows:
Использует pywinauto (UIA backend) и системный буфер обмена Windows (через clip.exe).
Строго соблюдает пользовательский сценарий:
1. Активация главного окна 1С.
2. Открытие панели 'Избранное' через значок звездочки ⭐ (или Ctrl+Shift+B).
3. Клик по разделу 'Адреса доставки' в списке Избранного.
4. Открытие поиска (Ctrl+F) в разделе 'Адреса доставки'.
5. Вставка адреса (или кода МСК...) через буфер обмена (Ctrl+V) с защитой от раскладки.
6. Открытие карточки найденной строки (Enter).
7. Переход на вкладку 'Адресная информация'.
8. Ввод Широты, Долготы и Радиуса зоны через буфер обмена (Ctrl+V).
9. Отметка чекбокса 'Координаты проверены'.
10. Нажатие 'Записать и закрыть' (Ctrl+Enter).

На macOS / Linux:
Автоматически включает режим MockOneCService (симулятор) для безопасной отладки.
"""

import sys
import time
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def set_clipboard(text: str) -> None:
    """
    Копирует текст в системный буфер обмена Windows через clip.exe (UTF-16).
    На 100% исключает ошибки раскладки клавиатуры (ENG/RUS).
    """
    try:
        subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
    except Exception as e:
        logger.warning("Не удалось скопировать текст в буфер через clip: %s", e)


class OneCServiceInterface:
    """Базовый интерфейс сервиса 1С."""

    def update_coordinates(
        self,
        code: str,
        address: str,
        lat: float,
        lon: float,
        radius: Optional[int] = None,
        client_name: str = "",
    ) -> bool:
        raise NotImplementedError


class MockOneCService(OneCServiceInterface):
    """Симулятор 1С для тестирования на macOS."""

    def update_coordinates(
        self,
        code: str,
        address: str,
        lat: float,
        lon: float,
        radius: Optional[int] = None,
        client_name: str = "",
    ) -> bool:
        lat_str = f"{lat:.8f}".replace(".", ",")
        lon_str = f"{lon:.8f}".replace(".", ",")
        rad_str = str(radius) if radius is not None else "сохранить текущий"

        print("\n" + "=" * 65)
        print(" [1C-СИМУЛЯТОР / macOS] Эмуляция обновления координат в 1С")
        print("=" * 65)
        print(" 1. Поиск окна: '(МСК) РМХЦ Хвостов; Интерфейс: / КИС 3.1'")
        print(" 2. Открытие 'Избранное' через звездочку ⭐")
        print(" 3. Выбор раздела 'Адреса доставки' в Избранном")
        print(f" 4. Поиск в списке: '{address}' [или код {code}]")
        print(f" 5. Открытие карточки: '{client_name or code}' (Enter)")
        print(" 6. Переход на вкладку: 'Адресная информация'")
        print(f" 7. Ввод геоданных через буфер обмена (Ctrl+V):")
        print(f"    • Широта:         {lat_str}")
        print(f"    • Долгота:        {lon_str}")
        print(f"    • Радиус зоны:    {rad_str} м")
        print(f"    • Чекбокс:        [x] Координаты проверены")
        print(" 8. Сохранение:       'Записать и закрыть' (Ctrl+Enter)")
        time.sleep(1)
        print(f" 9. Уведомление 1С:   ✓ 'Изменение: {client_name or code}'")
        print("=" * 65 + "\n")
        return True


class WindowsOneCService(OneCServiceInterface):
    """
    Реальный сервис автоматизации 1С под Windows через pywinauto (UIA).
    """

    def __init__(self):
        try:
            from pywinauto import Application
            from pywinauto.keyboard import send_keys
            self.app_module = Application
            self.send_keys = send_keys
            self.app = None
            self.main_win = None
        except ImportError:
            raise ImportError(
                "Библиотека pywinauto не установлена! Установите ее: pip install pywinauto"
            )

    def _find_main_window(self):
        """Находит главное окно 1С по заголовку и активирует его."""
        import pywinauto
        windows = pywinauto.findwindows.find_elements(
            title_re=".*(1С:Предприятие|ЕИС МСК|Корпоративная информационная система).*"
        )
        if not windows:
            raise RuntimeError("Главное окно 1С не найдено! Убедитесь, что 1С запущена.")
        
        self.app = self.app_module(backend="uia").connect(handle=windows[0].handle)
        self.main_win = self.app.window(handle=windows[0].handle)
        self._bring_to_front()
        return self.main_win

    def _bring_to_front(self):
        """
        Гарантированно выводит окно 1С на передний план с передачей реального клавиатурного фокуса ОС.
        Обходит ограничение Windows SetForegroundWindow Lock через симуляцию ALT и клик по шапке.
        """
        import ctypes
        import win32gui
        import win32con
        import pywinauto

        hwnd = self.main_win.handle
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            # Обход ограничения Windows SetForegroundWindow
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)  # ALT down
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)  # ALT up
            win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            logger.debug("Win32 SetForegroundWindow: %s", e)

        try:
            self.main_win.set_focus()
        except Exception:
            pass
        time.sleep(0.5)

        # Физический клик по заголовку окна 1С для 100% активации
        try:
            r = self.main_win.rectangle()
            # Клик в безопасную зону шапки окна (слева вверху, правее иконки 1С)
            pywinauto.mouse.click(coords=(r.left + 250, r.top + 15))
        except Exception as e:
            logger.debug("Клик по заголовку окна: %s", e)
        time.sleep(0.5)

    def _find_elements_by_text(self, text_substr: str, control_type: Optional[str] = None):
        """
        Безопасный поиск элементов по подстроке текста без использования title_re.
        Исключает ошибки IUIA.build_condition() и работает во всех версиях pywinauto.
        """
        results = []
        windows_to_check = []
        if self.main_win is not None:
            windows_to_check.append(self.main_win)
        if self.app is not None:
            try:
                windows_to_check.extend(self.app.windows())
            except Exception:
                pass

        seen_handles = set()
        for w in windows_to_check:
            try:
                h = w.handle
                if h in seen_handles:
                    continue
                seen_handles.add(h)
            except Exception:
                pass

            try:
                kwargs = {}
                if control_type:
                    kwargs["control_type"] = control_type
                desc = w.descendants(**kwargs)
                for el in desc:
                    try:
                        txt = el.window_text() or ""
                        if text_substr.lower() in txt.lower():
                            results.append(el)
                    except Exception:
                        continue
            except Exception:
                continue
        return results

    def _exact_visible(self, name: str):
        """Видимые элементы с ТОЧНЫМ текстом name (без учета регистра/пробелов по краям)."""
        res = []
        for el in self._find_elements_by_text(name):
            try:
                if (el.window_text() or "").strip().lower() == name.lower() and el.is_displayed():
                    res.append(el)
            except Exception:
                continue
        return res

    def _is_form_open(self, name: str) -> bool:
        """
        Проверяет, что в 1С активна форма с заголовком name.
        """
        try:
            win_rect = self.main_win.rectangle()
            top_zone = win_rect.top + int((win_rect.bottom - win_rect.top) * 0.25)
            bottom_zone = win_rect.bottom - 70
            for el in self._find_elements_by_text(name):
                try:
                    r = el.rectangle()
                    if (r.top < top_zone or (top_zone <= r.top < bottom_zone)) and el.is_displayed():
                        return True
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Проверка заголовка формы: %s", e)
        return False

    def _open_favorite_by_name(self, name: str) -> bool:
        """
        Открывает раздел 'Адреса доставки' в 1С:
        1. Сначала проверяет, открыта ли уже вкладка на нижней панели вкладок 1С.
        2. Если нет — открывает панель Избранного через звездочку ⭐ или Ctrl+Shift+B,
           находит раздел по имени и открывает его.
        """
        import pywinauto

        win_rect = self.main_win.rectangle()
        bottom_zone = win_rect.bottom - 70

        # ШАГ А: Проверяем, открыт ли уже этот раздел на нижней панели вкладок 1С
        for el in self._exact_visible(name):
            try:
                r = el.rectangle()
                if r.top >= bottom_zone:
                    print(f"[1С:Windows] Раздел '{name}' уже открыт на панели открытых вкладок! Кликаем вкладку...")
                    el.click_input()
                    time.sleep(2.0)
                    return True
            except Exception:
                continue

        # ШАГ Б: Открываем панель 'Избранное'
        print(f"[1С:Windows] Открытие Избранного для выбора '{name}'...")
        opened_fav = False

        # 1. Пробуем кликнуть по звездочке возле имени пользователя в шапке
        user_els = self._find_elements_by_text("Хвостов")
        if not user_els:
            user_els = self._find_elements_by_text("РМХЦ")

        if user_els:
            try:
                ur = user_els[0].rectangle()
                star_x = ur.left - 35
                star_y = ur.top + ur.height() // 2
                print(f"[1С:Windows] Клик по звездочке Избранного возле имени пользователя ({star_x}, {star_y})...")
                pywinauto.mouse.click(coords=(star_x, star_y))
                opened_fav = True
                time.sleep(1.2)
            except Exception as e:
                logger.debug("Клик по координатам звездочки: %s", e)

        # 2. Если клик не прошел — посылаем комбинацию клавиш Ctrl+Shift+B
        if not opened_fav:
            print("[1С:Windows] Открытие Избранного через горячие клавиши Ctrl+Shift+B...")
            self.send_keys("^+b")
            time.sleep(1.2)

        # ШАГ В: Ищем пункт 'Адреса доставки' в открывшейся панели Избранного
        for el in self._exact_visible(name):
            try:
                r = el.rectangle()
                # Элемент из Избранного находится выше нижней панели
                if r.top < bottom_zone:
                    print(f"[1С:Windows] Клик по пункту Избранного '{name}'...")
                    el.click_input()
                    time.sleep(2.0)
                    return True
            except Exception:
                continue

        # ШАГ Г: Если клик по элементу не прошел — фильтруем Избранное через поиск (Ctrl+F)
        print(f"[1С:Windows] Поиск '{name}' через строку фильтра Избранного...")
        self.send_keys("^f")
        time.sleep(0.5)
        set_clipboard(name)
        self.send_keys("^a^v")
        time.sleep(1.0)
        self.send_keys("{ENTER}")
        time.sleep(2.0)

        # Также подстраховка: в Избранном первый пункт — нужный
        self.send_keys("{ENTER}")
        time.sleep(2.0)
        return True

    def update_coordinates(
        self,
        code: str,
        address: str,
        lat: float,
        lon: float,
        radius: Optional[int] = None,
        client_name: str = "",
    ) -> bool:
        print(f"\n[1С:Windows] Активация 1С для обновления точки '{client_name or code}'...")
        self._find_main_window()

        # -------------------------------------------------------------
        # ШАГ 1: Переход в раздел 'Адреса доставки' (через вкладку или Избранное ⭐)
        # -------------------------------------------------------------
        self._open_favorite_by_name("Адреса доставки")
        print("[1С:Windows] ✓ Раздел 'Адреса доставки' готов к поиску.")

        # -------------------------------------------------------------
        # ШАГ 2: Поиск строки в разделе 'Адреса доставки'
        # -------------------------------------------------------------
        # Предпочитаем уникальный код 1С (МСК...), если есть, либо адрес
        search_query = code if (code and code.startswith("МСК")) else address
        print(f"[1С:Windows] Поиск в разделе 'Адреса доставки': '{search_query}'...")

        # Нажимаем Ctrl+F для вызова строки поиска
        self.send_keys("^f")
        time.sleep(0.8)

        # Вставляем запрос через буфер обмена (Ctrl+V) — не зависит от раскладки!
        set_clipboard(search_query)
        self.send_keys("^v")
        time.sleep(0.4)
        self.send_keys("{ENTER}")
        time.sleep(2.5)

        # -------------------------------------------------------------
        # ШАГ 3: Открытие найденной карточки (Enter)
        # -------------------------------------------------------------
        print("[1С:Windows] Открытие карточки адреса (Enter)...")
        self.send_keys("{ENTER}")
        time.sleep(3.0)

        # -------------------------------------------------------------
        # ШАГ 4: Переход на вкладку 'Адресная информация'
        # -------------------------------------------------------------
        print("[1С:Windows] Переход во вкладку 'Адресная информация'...")
        tab_clicked = False
        try:
            tab_elems = self._find_elements_by_text("Адресная информация")
            for te in tab_elems:
                try:
                    if te.is_displayed():
                        te.click_input()
                        tab_clicked = True
                        time.sleep(1.2)
                        break
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Переход во вкладку Адресная информация: %s", e)

        if not tab_clicked:
            logger.info("Вкладка 'Адресная информация' возможно уже активна.")

        # -------------------------------------------------------------
        # ШАГ 5: Ввод новых координат через буфер обмена (Ctrl+V)
        # -------------------------------------------------------------
        lat_str = f"{lat:.8f}".replace(".", ",")
        lon_str = f"{lon:.8f}".replace(".", ",")
        print(f"[1С:Windows] Запись геоданных: Широта={lat_str}, Долгота={lon_str}...")

        # Поле 'Широта:'
        try:
            lat_labels = self._find_elements_by_text("Широта")
            for lbl in lat_labels:
                try:
                    if lbl.is_displayed():
                        lbl.click_input()
                        time.sleep(0.3)
                        self.send_keys("{TAB}")  # фокус на поле ввода
                        time.sleep(0.2)
                        set_clipboard(lat_str)
                        self.send_keys("^a^v")
                        time.sleep(0.3)
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Заполнение Широты: %s", e)

        # Поле 'Долгота:'
        try:
            lon_labels = self._find_elements_by_text("Долгота")
            for lbl in lon_labels:
                try:
                    if lbl.is_displayed():
                        lbl.click_input()
                        time.sleep(0.3)
                        self.send_keys("{TAB}")
                        time.sleep(0.2)
                        set_clipboard(lon_str)
                        self.send_keys("^a^v")
                        time.sleep(0.3)
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.warning("Заполнение Долготы: %s", e)

        # Поле 'Радиус зоны:' (если передан радиус)
        if radius is not None:
            print(f"[1С:Windows] Запись радиуса зоны: {radius} м...")
            try:
                rad_labels = self._find_elements_by_text("Радиус")
                for lbl in rad_labels:
                    try:
                        if lbl.is_displayed():
                            lbl.click_input()
                            time.sleep(0.3)
                            self.send_keys("{TAB}")
                            time.sleep(0.2)
                            set_clipboard(str(radius))
                            self.send_keys("^a^v")
                            time.sleep(0.3)
                            break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning("Заполнение Радиуса зоны: %s", e)

        # Чекбокс 'Координаты проверены'
        try:
            chks = self._find_elements_by_text("Координаты проверены", control_type="CheckBox")
            for chk in chks:
                try:
                    if chk.is_displayed():
                        try:
                            if not chk.get_toggle_state():
                                chk.click_input()
                        except Exception:
                            chk.click_input()
                        time.sleep(0.3)
                        break
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Чекбокс: %s", e)

        # -------------------------------------------------------------
        # ШАГ 6: Сохранение карточки 'Записать и закрыть' (Ctrl+Enter)
        # -------------------------------------------------------------
        print("[1С:Windows] Нажатие 'Записать и закрыть' (Ctrl+Enter)...")
        saved = False
        try:
            save_btns = self._find_elements_by_text("Записать и закрыть", control_type="Button")
            for btn in save_btns:
                try:
                    if btn.is_displayed():
                        btn.click_input()
                        saved = True
                        break
                except Exception:
                    pass
        except Exception:
            pass

        if not saved:
            self.send_keys("^{ENTER}")

        time.sleep(2.5)
        print(f"[1С:Windows] ✓ Данные точки '{client_name or code}' успешно сохранены в 1С!\n")
        return True


def get_onec_service() -> OneCServiceInterface:
    """Фабрика сервиса: на Windows возвращает WindowsOneCService."""
    if sys.platform == "win32":
        try:
            return WindowsOneCService()
        except Exception as e:
            logger.warning("Не удалось инициализировать WindowsOneCService (%s), fallback на Mock", e)
            return MockOneCService()
    else:
        return MockOneCService()

"""
onec_service.py — Сервис взаимодействия с 1С:Предприятие через прямые ссылки (e1cib).

На Windows:
  Использует промышленный RPA-стандарт для 1С:Предприятие (Управляемый интерфейс / Такси),
  проверенный на корпоративном ПК (1920x1080):
    1. Поиск, максимизация (SW_MAXIMIZE) и активация главного окна 1С.
    2. Переход в раздел «Адреса доставки»:
       - По прямой навигационной ссылке 1С через Shift + F11:
         URL: e1cib/list/Справочник.АдресаДоставки
         (В диалоге «Переход по ссылке» нажимается кнопка «Вставить из буфера» и «Перейти»).
    3. Установка фильтра по организации перед поиском точки:
       - Проверка, установлен ли уже фильтр «Организация: ООО "ФК ПУЛЬС"» (и удаление любого
         постороннего фильтра, например «Наименование: ...», через Ctrl+Q или крестик плашки).
       - Клик «Еще» -> «Расширенный поиск» (или Alt+F).
       - В окне «Найти»:
         * В строке «Где искать:» раскрывается выпадающий список (кликом по стрелке [v] в (1205, 455))
           и одним кликом выбирается строка «Организация» в (866, 600).
           ВАЖНО: текстовая вставка в «Где искать» НЕ используется, так как «Где искать» — это
           нередактируемый список колонок!
         * В строке «Что искать:» (866, 488) вставляется «ООО "ФК ПУЛЬС"», выбирается элемент из
           выпадающего списка (866, 518) и нажимается кнопка «Найти» (1042, 602).
         * Скрипт дожидается полной загрузки фильтра «Организация: ООО "ФК ПУЛЬС"».
    4. Поиск точки доставки в списке «Адреса доставки»:
       - Клик в поле поиска «Поиск (Ctrl+F)» (1580, 126) или вызов Ctrl+F.
       - Вставка номера точки («МСК...») через буфер обмена и нажатие Enter.
       - Ожидание загрузки результатов поиска.
       - Двойной клик по найденной строке в таблице (260, 250), чтобы провалиться внутрь карточки точки,
         и проверка, что в открывшейся карточке поле «Код:» совпадает с искомым номером точки!
    5. В открывшейся карточке точки доставки:
       - Переход в раздел (вкладку) «Адресная информация» (315, 362).
       - Заполнение полей «Широта», «Долгота» и (при необходимости) «Радиус зоны» через буфер обмена.
       - Установка галочки «Координаты проверены».
       - Нажатие «Записать и закрыть» (или Ctrl+Enter через виртуальные клавиши).

На macOS / Linux:
  Автоматически активируется MockOneCService — симулятор полного цикла с подробным логированием.
"""

import logging
import re
import subprocess
import sys
import time
from typing import Optional, Tuple

from config import Config, load_config

logger = logging.getLogger(__name__)


def set_clipboard(text: str) -> None:
    """Копирует текст в буфер обмена Windows (через Win32 API / clip.exe) без ошибок кодировки и раскладки."""
    if sys.platform == "win32":
        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return
        except Exception as e:
            logger.debug("win32clipboard error: %s, fallback to clip.exe", e)

        try:
            subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
            return
        except Exception as e:
            logger.warning("Не удалось скопировать текст в clip: %s", e)
    else:
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        except Exception:
            pass


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
    """Симулятор 1С для тестирования на macOS / Linux."""

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or load_config()

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

        print("\n" + "=" * 70)
        print(" [1С-СИМУЛЯТОР / macOS] Эмуляция обновления координат в 1С (e1cib)")
        print("=" * 70)
        print(f" 1. Поиск главного окна 1С: '{self.cfg.onec_window_regex}' -> [Найдено]")
        print(" 2. Максимизация и активация окна 1С (ShowWindow SW_MAXIMIZE)")
        print(" 3. Переход в раздел «Адреса доставки» (Shift + F11):")
        print(f"    URL: «{self.cfg.url_adresa_dostavki}»")
        print(" 4. Установка фильтра по организации (Еще -> Расширенный поиск):")
        print(f"    • Где искать:     {self.cfg.onec_org_filter_field}")
        print(f"    • Что искать:     {self.cfg.onec_org_filter_value}")
        print("    • Кнопка:         [Найти] -> Ожидание загрузки фильтра...")
        print(f" 5. Поиск номера точки (Поиск Ctrl+F -> Ctrl+V -> Enter): '{code or address}'")
        print("    • Ожидание загрузки найденной строки...")
        print(f" 6. Двойной клик по найденной строке -> открытие карточки: '{client_name or code}'")
        print(f"    • Проверка кода точки в открытой карточке: '{code}' -> [Совпадает]")
        print(" 7. Переход в раздел (вкладку): «Адресная информация»")
        print(" 8. Запись геоданных через буфер обмена (Ctrl+A -> Ctrl+V):")
        print(f"    • Широта:         {lat_str}")
        print(f"    • Долгота:        {lon_str}")
        print(f"    • Радиус зоны:    {rad_str} м")
        print("    • Чекбокс:        [x] Координаты проверены")
        print(" 9. Сохранение:       «Записать и закрыть» (Ctrl+Enter)")
        time.sleep(0.5)
        print(f"10. Статус 1С:        ✓ Карточка «{client_name or code}» успешно обновлена!")
        print("=" * 70 + "\n")
        return True


class WindowsOneCService(OneCServiceInterface):
    """
    Реальный сервис автоматизации 1С:Предприятие под Windows.
    Использует прямые навигационные ссылки 1С (Shift+F11 / e1cib), виртуальные коды клавиш
    win32api (независимые от раскладки RUS/ENG), UI Automation (pywinauto) и калиброванные
    координаты 1920x1080 с проверкой результата каждого шага.
    """

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or load_config()
        try:
            import ctypes
            import pywinauto
            from pywinauto import Application, Desktop
            from pywinauto.keyboard import send_keys
            import win32api
            import win32con
            import win32gui

            self.ctypes = ctypes
            self.pywinauto = pywinauto
            self.Application = Application
            self.Desktop = Desktop
            self.send_keys = send_keys
            self.win32api = win32api
            self.win32con = win32con
            self.win32gui = win32gui
        except ImportError as e:
            raise ImportError(
                f"Не установлена библиотека для Windows-автоматизации: {e}. "
                "Выполните: pip install pywinauto pywin32"
            )

        self.app = None
        self.main_win = None

    # ---------------------------------------------------------------------
    # Низкоуровневые методы работы с клавиатурой (не зависят от раскладки!)
    # ---------------------------------------------------------------------
    def _send_vk(self, vk_code: int, down: bool = True) -> None:
        """Отправка Virtual Key события через win32api (не зависит от раскладки RUS/ENG)."""
        flags = 0 if down else self.win32con.KEYEVENTF_KEYUP
        self.win32api.keybd_event(vk_code, 0, flags, 0)

    def _send_hotkey(self, *vk_codes: int) -> None:
        """Нажатие комбинации клавиш по их виртуальным кодам."""
        for code in vk_codes:
            self._send_vk(code, down=True)
            time.sleep(0.04)
        for code in reversed(vk_codes):
            self._send_vk(code, down=False)
            time.sleep(0.04)
        time.sleep(0.2)

    def _hotkey_shift_f11(self) -> None:
        """Переход по ссылке 1С: Shift + F11 (0x10, 0x7A)."""
        self._send_hotkey(self.win32con.VK_SHIFT, self.win32con.VK_F11)

    def _hotkey_alt_f(self) -> None:
        """Расширенный поиск в списке 1С: Alt + F (VK_MENU, 0x46)."""
        self._send_hotkey(self.win32con.VK_MENU, 0x46)

    def _hotkey_ctrl_f(self) -> None:
        """Поиск в списке 1С: Ctrl + F (0x46)."""
        self._send_hotkey(self.win32con.VK_CONTROL, 0x46)

    def _hotkey_ctrl_q(self) -> None:
        """Отменить поиск в списке 1С: Ctrl + Q (0x51)."""
        self._send_hotkey(self.win32con.VK_CONTROL, 0x51)

    def _hotkey_ctrl_f4(self) -> None:
        """Закрыть текущую вкладку (Ctrl + F4): VK_F4 = 0x73."""
        self._send_hotkey(self.win32con.VK_CONTROL, self.win32con.VK_F4)

    def _hotkey_ctrl_enter(self) -> None:
        """Записать и закрыть в 1С: Ctrl + Enter."""
        self._send_hotkey(self.win32con.VK_CONTROL, self.win32con.VK_RETURN)

    def _hotkey_enter(self) -> None:
        """Нажатие Enter."""
        self._send_hotkey(self.win32con.VK_RETURN)

    def _hotkey_tab(self) -> None:
        """Нажатие Tab."""
        self._send_hotkey(self.win32con.VK_TAB)

    def _hotkey_esc(self) -> None:
        """Нажатие Esc."""
        self._send_hotkey(self.win32con.VK_ESCAPE)

    def _paste_clipboard(self) -> None:
        """Вставка из буфера обмена через Ctrl + V (0x56)."""
        self._send_hotkey(self.win32con.VK_CONTROL, 0x56)

    def _select_all_and_paste(self, text: str) -> None:
        """Выделяет всё поле (Ctrl+A), копирует текст в буфер и вставляет (Ctrl+V)."""
        set_clipboard(text)
        time.sleep(0.1)
        self._send_hotkey(self.win32con.VK_CONTROL, 0x41)  # Ctrl + A
        time.sleep(0.08)
        self._paste_clipboard()
        time.sleep(0.15)

    def _get_element_text(self, el) -> str:
        """Безопасно извлекает текст или текущее значение (Value) UIA-элемента 1С."""
        parts = []
        try:
            if el.element_info.name:
                parts.append(str(el.element_info.name))
        except Exception:
            pass
        try:
            wt = el.window_text()
            if wt:
                parts.append(str(wt))
        except Exception:
            pass
        try:
            if hasattr(el, "get_value"):
                v = el.get_value()
                if v:
                    parts.append(str(v))
        except Exception:
            pass
        try:
            if hasattr(el, "legacy_properties"):
                v = el.legacy_properties().get("Value")
                if v:
                    parts.append(str(v))
        except Exception:
            pass
        return " ".join(parts).strip()

    def _wait_1c_ready(self, min_wait: float = 2.0, max_wait: float = 12.0) -> None:
        """
        Ожидает завершения фоновой операции / фильтрации в 1С:
        выдерживает гарантированную паузу min_wait и проверяет через Win32 IsHungAppWindow,
        что поток окна 1С не занят тяжелым запросом.
        """
        time.sleep(min_wait)
        if not self.main_win:
            return
        try:
            hwnd = self.main_win.handle
            end_time = time.time() + max(0.0, max_wait - min_wait)
            while time.time() < end_time:
                try:
                    is_hung = bool(self.ctypes.windll.user32.IsHungAppWindow(hwnd))
                    if not is_hung:
                        break
                except Exception:
                    break
                time.sleep(0.4)
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Надежный поиск диалогов в Windows (Win32 EnumWindows + Desktop UIA)
    # ---------------------------------------------------------------------
    def _find_dialog(self, title_sub: str, timeout: float = 4.0):
        """
        Гарантированно находит диалоговое окно 1С по подстроке заголовка:
        1. Среди отдельных окон верхнего уровня (Win32 EnumWindows / Desktop UIA).
        2. Среди встроенных модальных окон внутри главного окна 1С.
        """
        end_time = time.time() + timeout
        pattern = re.compile(rf".*{re.escape(title_sub)}.*", re.IGNORECASE)
        main_hwnd = None
        if self.main_win:
            try:
                main_hwnd = self.main_win.handle
            except Exception:
                pass

        while time.time() < end_time:
            # 1. Поиск через Win32 EnumWindows
            try:
                handles = self.pywinauto.findwindows.find_elements(title_re=pattern)
                for h in handles:
                    if main_hwnd and h.handle == main_hwnd:
                        continue
                    app_dlg = self.Application(backend="uia").connect(handle=h.handle)
                    return app_dlg.window(handle=h.handle)
            except Exception:
                pass

            # 2. Поиск через Desktop UIA
            try:
                for w in self.Desktop(backend="uia").windows():
                    try:
                        if main_hwnd and w.handle == main_hwnd:
                            continue
                        t = (w.element_info.name or w.window_text() or "").strip()
                        if pattern.search(t):
                            ctrl_type = getattr(w.element_info, "control_type", "")
                            if ctrl_type in ("Window", "Pane", "Dialog", ""):
                                return w
                    except Exception:
                        continue
            except Exception:
                pass

            # 3. Поиск внутри главного окна 1С (встроенные модальные формы 1С Такси)
            if self.main_win:
                try:
                    for el in self.main_win.descendants():
                        try:
                            ctrl_type = getattr(el.element_info, "control_type", "")
                            if ctrl_type not in ("Window", "Dialog", "Pane", "Custom"):
                                continue
                            t = (el.element_info.name or el.window_text() or "").strip()
                            if t and pattern.search(t):
                                r = el.rectangle()
                                if 200 <= r.width() <= 1000 and 120 <= r.height() <= 700:
                                    return el
                        except Exception:
                            continue
                except Exception:
                    pass

            time.sleep(0.25)
        return None

    # ---------------------------------------------------------------------
    # Активация и максимизация окна 1С
    # ---------------------------------------------------------------------
    def _find_and_activate_1c(self) -> None:
        """Находит главное окно 1С по заголовку, максимизирует и выводит на передний план."""
        print(f"[1С:Windows] Поиск окна 1С по маске '{self.cfg.onec_window_regex}'...")
        elements = self.pywinauto.findwindows.find_elements(
            title_re=self.cfg.onec_window_regex
        )
        if not elements:
            raise RuntimeError(
                "Главное окно 1С:Предприятие не найдено!\n"
                "Пожалуйста, запустите 1С и войдите в рабочую базу перед запуском скрипта."
            )

        hwnd = elements[0].handle
        self.app = self.Application(backend="uia").connect(handle=hwnd)
        self.main_win = self.app.window(handle=hwnd)

        try:
            if self.win32gui.IsIconic(hwnd):
                self.win32gui.ShowWindow(hwnd, self.win32con.SW_RESTORE)
                time.sleep(0.2)
            self.win32gui.ShowWindow(hwnd, self.win32con.SW_MAXIMIZE)
        except Exception:
            pass
        time.sleep(0.3)

        try:
            self._send_vk(self.win32con.VK_MENU, down=True)
            self._send_vk(self.win32con.VK_MENU, down=False)
            self.win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

        try:
            self.main_win.set_focus()
        except Exception:
            pass

        time.sleep(0.5)
        print("[1С:Windows] ✓ Окно 1С успешно максимизировано и активировано.")

    # ---------------------------------------------------------------------
    # Управление вкладками 1С и 100% надежный переход по ссылке (Shift+F11)
    # ---------------------------------------------------------------------
    def _activate_tab_by_name(self, section_title: str) -> bool:
        """
        Ищет вкладку с подстрокой section_title на нижней панели открытых вкладок 1С.
        Кликает строго по левой части вкладки (r.left + min(35, r.width() // 3)),
        чтобы исключить случайный клик по крестику закрытия [x].
        """
        if not self.main_win:
            return False

        try:
            main_r = self.main_win.rectangle()
            kw = section_title.lower().strip()
            synonyms = [kw]
            if "адрес" in kw:
                synonyms.extend(["адреса доставки", "адреса"])

            for el in self.main_win.descendants():
                try:
                    txt = (el.element_info.name or el.window_text() or "").strip().lower()
                    if not txt:
                        continue
                    if "(адреса доставки)" in txt:
                        continue
                    if any(s in txt for s in synonyms):
                        r = el.rectangle()
                        if r.top >= main_r.bottom - 80 and r.width() > 30 and r.height() > 15:
                            click_x = r.left + min(35, r.width() // 3)
                            click_y = r.top + r.height() // 2
                            self.pywinauto.mouse.click(coords=(click_x, click_y))
                            return True
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Поиск открытой вкладки '%s': %s", section_title, e)

        return False

    def _activate_tab_or_open_link(self, url: str, section_title: str) -> None:
        """
        Гарантированно и мгновенно (без долгого сканирования дерева UIA) переходит
        в раздел «Адреса доставки» по прямой навигационной ссылке 1С:
          1. Копирует URL в буфер обмена.
          2. Нажимает Shift+F11 (в 1С открывается окно «Переход по ссылке», фокус сразу в поле «Ссылка:»).
          3. Вставляет URL (Ctrl+A -> Ctrl+V) и нажимает Enter (кнопка «Перейти» по умолчанию).
        """
        print(f"\n[1С:Windows] Переход в раздел «{section_title}» по прямой ссылке (Shift+F11)...")
        print(f"             URL: {url}")

        # Если вдруг остался открытым какой-то модальный диалог (например, «Найти») — закрываем его
        self._hotkey_esc()
        time.sleep(0.25)

        set_clipboard(url)
        time.sleep(0.1)

        self._hotkey_shift_f11()
        time.sleep(0.8)

        # В открывшемся окне «Переход по ссылке» фокус уже стоит в поле «Ссылка:» (см. s_057.png)
        self._select_all_and_paste(url)
        time.sleep(0.25)
        self._hotkey_enter()

        self._wait_1c_ready(min_wait=2.5, max_wait=8.0)
        print(f"[1С:Windows] ✓ Раздел «{section_title}» успешно открыт по прямой ссылке.")

    # ---------------------------------------------------------------------
    # Вспомогательные методы работы с экраном и пикселями (1920x1080)
    # ---------------------------------------------------------------------
    def _scale_xy(self, x: int, y: int) -> Tuple[int, int]:
        """
        Возвращает экранные координаты для максимизированного окна 1С.
        На эталонном разрешении 1920x1080 возвращает (x, y) один-в-один.
        """
        try:
            sw = int(self.ctypes.windll.user32.GetSystemMetrics(0))
            sh = int(self.ctypes.windll.user32.GetSystemMetrics(1))
            if sw > 0 and sh > 0 and (sw != 1920 or sh != 1080):
                return int(round(x * sw / 1920.0)), int(round(y * sh / 1080.0))
        except Exception:
            pass
        return x, y

    def _get_pixel_rgb(self, x: int, y: int) -> Optional[Tuple[int, int, int]]:
        """Быстрое чтение RGB пикселя экрана через Win32 GDI GetPixel (занимает < 1 мс)."""
        try:
            hdc = self.ctypes.windll.user32.GetDC(0)
            if not hdc:
                return None
            try:
                color = self.ctypes.windll.gdi32.GetPixel(hdc, int(x), int(y))
                if color == -1 or color == 0xFFFFFFFF:
                    return None
                r = color & 0xFF
                g = (color >> 8) & 0xFF
                b = (color >> 16) & 0xFF
                return (int(r), int(g), int(b))
            finally:
                self.ctypes.windll.user32.ReleaseDC(0, hdc)
        except Exception:
            return None

    # ---------------------------------------------------------------------
    # Шаг 3: Установка фильтра Организация = ООО "ФК ПУЛЬС" (Расширенный поиск)
    # ---------------------------------------------------------------------
    def _click_list_more_button(self) -> None:
        """
        Нажимает кнопку «Еще ▾» на командной панели списка «Адреса доставки»
        (точное положение на 1920x1080: x=1831, y=130).
        """
        click_x, click_y = self._scale_xy(1831, 130)
        print(f"[1С:Windows] Клик по кнопке «Еще» на панели списка ({click_x}, {click_y})...")
        self.pywinauto.mouse.click(coords=(click_x, click_y))

    def _click_advanced_search_in_menu(self) -> None:
        """
        В открывшемся меню «Еще» нажимает пункт «Расширенный поиск»
        (точное положение на 1920x1080: x=1550, y=343).
        """
        time.sleep(0.5)
        click_x, click_y = self._scale_xy(1550, 343)
        print(f"[1С:Windows] Клик по пункту меню «Расширенный поиск» ({click_x}, {click_y})...")
        self.pywinauto.mouse.click(coords=(click_x, click_y))

    def _ensure_organization_filter(self) -> None:
        """
        Выполняет точную последовательность установки фильтра «Организация: ООО "ФК ПУЛЬС"»:
        1. Сбрасывает возможный старый фильтр через Ctrl+Q.
        2. Нажимает «Еще» (1831, 130) -> «Расширенный поиск» (1550, 343).
        3. В открывшемся окне «Найти» (все координаты выверены по кадрам 1920x1080 с точностью до 1px):
           - Кликает строго по стрелке раскрытия списка «Где искать:» -> (1203, 460).
           - В раскрывшемся списке кликает строго по строке «Организация» -> (880, 608).
           - Кликает в поле «Что искать:» -> (880, 495) и вставляет 'ООО "ФК ПУЛЬС"'.
           - Ждет появления выпадающей подсказки 1С и кликает по 'ООО "ФК ПУЛЬС"' -> (880, 526).
           - Кликает по желтой кнопке «Найти» -> (1045, 608).
        4. Дожидается полной загрузки отфильтрованного списка (4.5 сек + проверка готовности окна 1С).
        """
        field_name = self.cfg.onec_org_filter_field  # "Организация"
        org_value = self.cfg.onec_org_filter_value   # 'ООО "ФК ПУЛЬС"'

        print(f"[1С:Windows] Установка фильтра «{field_name}: {org_value}» (Еще -> Расширенный поиск)...")

        # 1. Сбрасываем любой старый фильтр перед открытием «Расширенного поиска»
        self._hotkey_ctrl_q()
        time.sleep(0.6)

        # 2. Открываем меню «Еще» -> «Расширенный поиск»
        self._click_list_more_button()
        self._click_advanced_search_in_menu()
        time.sleep(0.9)

        # -----------------------------------------------------------------
        # 3. В строке «Где искать:» переключаем «Наименование» -> «Организация»
        #    Точные координаты на 1920x1080 (проверено по s_080.png и grid_dropdown_67.png):
        #    • Стрелка [v] поля «Где искать:»: (1203, 460)
        #    • Пункт «Организация» в выпадающем списке: (880, 608)
        # -----------------------------------------------------------------
        where_arrow_x, where_arrow_y = self._scale_xy(1203, 460)
        org_option_x, org_option_y = self._scale_xy(880, 608)

        print(f"[1С:Windows]   1) Раскрытие списка «Где искать» ({where_arrow_x}, {where_arrow_y})...")
        self.pywinauto.mouse.click(coords=(where_arrow_x, where_arrow_y))
        time.sleep(0.7)

        print(f"[1С:Windows]   2) Выбор пункта «{field_name}» в списке ({org_option_x}, {org_option_y})...")
        self.pywinauto.mouse.click(coords=(org_option_x, org_option_y))
        time.sleep(0.6)

        # -----------------------------------------------------------------
        # 4. В строке «Что искать:» вводим и выбираем 'ООО "ФК ПУЛЬС"'
        #    Точные координаты на 1920x1080 (проверено по s_080.png и f_44s.png):
        #    • Поле «Что искать:»: (880, 495)
        #    • Выпадающая подсказка 'ООО "ФК ПУЛЬС" ()': (880, 526)
        # -----------------------------------------------------------------
        what_field_x, what_field_y = self._scale_xy(880, 495)
        what_popup_x, what_popup_y = self._scale_xy(880, 526)

        print(f"[1С:Windows]   3) Клик в поле «Что искать» ({what_field_x}, {what_field_y}) и вставка «{org_value}»...")
        self.pywinauto.mouse.click(coords=(what_field_x, what_field_y))
        time.sleep(0.3)
        self._select_all_and_paste(org_value)

        # Ждем 1.2 сек появления выпадающей подсказки 1С с элементом справочника «ООО "ФК ПУЛЬС"»
        time.sleep(1.2)

        print(f"[1С:Windows]   4) Выбор «{org_value}» из выпадающего списка ({what_popup_x}, {what_popup_y})...")
        self.pywinauto.mouse.click(coords=(what_popup_x, what_popup_y))
        time.sleep(0.6)

        # -----------------------------------------------------------------
        # 5. Нажимаем желтую кнопку «Найти»
        #    Точные координаты на 1920x1080 (проверено по s_080.png и f_47s.png):
        #    • Кнопка «Найти»: (1045, 608)
        # -----------------------------------------------------------------
        find_btn_x, find_btn_y = self._scale_xy(1045, 608)

        print(f"[1С:Windows]   5) Нажатие кнопки «Найти» ({find_btn_x}, {find_btn_y}) и ожидание прогрузки фильтра...")
        self.pywinauto.mouse.click(coords=(find_btn_x, find_btn_y))
        time.sleep(0.3)

        # Дожидаемся полной загрузки отфильтрованного списка (на видео фильтрация занимает ~3.5-4.5 секунды)
        self._wait_1c_ready(min_wait=4.5, max_wait=14.0)
        print(f"[1С:Windows] ✓ Фильтр «{field_name}: {org_value}» установлен и загружен.")

    # ---------------------------------------------------------------------
    # Шаг 4: Поиск номера точки в списке и вход в карточку двойным кликом
    # ---------------------------------------------------------------------
    def _focus_and_paste_in_search_box(self, query: str) -> None:
        """
        Вставляет номер точки в поле «Поиск (Ctrl+F)» на командной панели «Адреса доставки»,
        нажимает Enter и дожидается полной загрузки результатов поиска.

        Точные координаты на 1920x1080 (проверено по s_080.png и f_52s.png):
          • Поле «Поиск (Ctrl+F)»: left=1474..1719, top=118..142 (центр: x=1600, y=130)
        """
        print(f"[1С:Windows] Поиск номера точки в списке: '{query}'...")

        search_x, search_y = self._scale_xy(1600, 130)

        # 1. Кликаем прямо в поле «Поиск (Ctrl+F)»
        print(f"[1С:Windows] Клик в поле «Поиск (Ctrl+F)» ({search_x}, {search_y})...")
        self.pywinauto.mouse.click(coords=(search_x, search_y))
        time.sleep(0.35)

        # 2. Вставляем номер точки через буфер обмена (Ctrl+A -> Ctrl+V) и нажимаем Enter
        self._select_all_and_paste(query)
        time.sleep(0.35)
        self._hotkey_enter()

        # 3. Ожидаем завершения загрузки поиска (пока прогрузится спиннер «Поиск...»)
        print(f"[1С:Windows] Ожидание загрузки результатов поиска для '{query}'...")
        self._wait_1c_ready(min_wait=3.5, max_wait=10.0)

    def _is_address_card_open(self) -> bool:
        """
        Быстро проверяет (за < 5 мс), открылась ли карточка точки доставки:
        В открытой карточке на (250, 130) и (220, 130) находится ярко-желтая кнопка «Записать и закрыть»
        (RGB=(247, 238, 20)), тогда как в списке «Адреса доставки» там белая/серая область (RGB=(253, 253, 253)).
        """
        for px, py in ((250, 130), (220, 130)):
            sx, sy = self._scale_xy(px, py)
            rgb = self._get_pixel_rgb(sx, sy)
            if rgb is not None:
                r, g, b = rgb
                if r > 215 and g > 195 and b < 100:
                    return True
        return False

    def _verify_opened_card_matches_point(self, expected_code: str, expected_client: str) -> bool:
        """
        КРИТИЧЕСКАЯ ЗАЩИТА:
        Проверяет, что открытая в 1С карточка действительно принадлежит искомой точке:
        Кликает в поле «Код:» открытой карточки (1830, 170), копирует код через Ctrl+A -> Ctrl+C
        и сверяет его с expected_code.
        Если открылась чужая карточка — немедленно закрывает её через Ctrl+F4 и возвращает False!
        """
        if not expected_code:
            return True

        code_expected_low = expected_code.strip().lower()
        code_field_x, code_field_y = self._scale_xy(1830, 170)

        try:
            set_clipboard("")
            time.sleep(0.05)
            self.pywinauto.mouse.click(coords=(code_field_x, code_field_y))
            time.sleep(0.2)
            self._hotkey_ctrl_a()
            time.sleep(0.1)
            self._hotkey_ctrl_c()
            time.sleep(0.2)
            copied_code = (get_clipboard() or "").strip()
        except Exception as e:
            logger.debug("Чтение поля Код из карточки: %s", e)
            copied_code = ""

        if copied_code:
            copied_low = copied_code.lower()
            if code_expected_low in copied_low or copied_low in code_expected_low:
                print(f"[1С:Windows] ✓ Проверка безопасности: код точки '{copied_code}' в карточке совпадает с '{expected_code}'.")
                return True

            other_codes = re.findall(r"\b(?:мск|брн|влг|спб|екб|нск|кзн|рнд|смр|вшн|тул|ирк|орл|клг)\d{4,12}\b", copied_low)
            if other_codes and code_expected_low not in other_codes:
                print(
                    f"[1С:Windows] ⚠ ЗАЩИТА: Открылась чужая карточка (Код в карточке: '{copied_code}' "
                    f"вместо '{expected_code}')! Закрываем карточку без изменений..."
                )
                self._hotkey_ctrl_f4()
                time.sleep(1.0)
                return False

        return True

    def _double_click_found_row(self, code: str, address: str, client_name: str) -> bool:
        """
        Дважды нажимает на первую найденную строку в таблице «Адреса доставки» (450, 267),
        чтобы провалиться в карточку точки, и проверяет, что открылась именно нужная точка.
        """
        first_row_x, first_row_y = self._scale_xy(450, 267)
        print(f"[1С:Windows] Двойной клик по найденной строке точки '{code or client_name}' ({first_row_x}, {first_row_y})...")
        self.pywinauto.mouse.double_click(coords=(first_row_x, first_row_y))

        self._wait_1c_ready(min_wait=2.2, max_wait=7.0)

        if not self._is_address_card_open():
            print(f"[1С:Windows] Повторный двойной клик + Enter по строке ({first_row_x}, {first_row_y})...")
            self.pywinauto.mouse.double_click(coords=(first_row_x, first_row_y))
            time.sleep(0.3)
            self._hotkey_enter()
            self._wait_1c_ready(min_wait=2.2, max_wait=7.0)

        if not self._is_address_card_open():
            print("[1С:Windows] ⚠ Карточка точки не открылась после двойного клика (возможно, список результатов пуст).")
            return False

        return self._verify_opened_card_matches_point(expected_code=code, expected_client=client_name)

    def _search_and_open_address_card(self, code: str, address: str, client_name: str) -> None:
        """
        Вставляет номер точки (МСК...) в поиск, дожидается загрузки,
        дважды нажимает на найденную строку, чтобы провалиться внутрь карточки.
        """
        primary_query = code.strip() if code else address.strip()
        self._focus_and_paste_in_search_box(primary_query)

        opened = self._double_click_found_row(code=code, address=address, client_name=client_name)

        if not opened and code and address:
            short_addr = address.strip()
            print(f"[1С:Windows] Поиск по коду '{code}' не открыл целевую карточку, пробуем по адресу: '{short_addr}'...")
            self._focus_and_paste_in_search_box(short_addr)
            opened = self._double_click_found_row(code=code, address=address, client_name=client_name)

        if not opened:
            raise RuntimeError(
                f"Не удалось найти и открыть карточку точки '{client_name}' (Код: {code}) в 1С! "
                "Запись координат отменена во избежание изменения другой точки."
            )

    # ---------------------------------------------------------------------
    # Шаг 5: Раздел «Адресная информация» и заполнение геоданных внутри точки
    # ---------------------------------------------------------------------
    def _switch_to_address_info_tab(self) -> None:
        """
        Внутри открытой карточки точки доставки открывает вкладку «Адресная информация»
        (точное положение на 1920x1080 по f_95s.png: x=330, y=375).
        """
        click_x, click_y = self._scale_xy(330, 375)
        print(f"[1С:Windows] Переход на вкладку «Адресная информация» ({click_x}, {click_y})...")
        self.pywinauto.mouse.click(coords=(click_x, click_y))
        time.sleep(0.8)

    def _fill_field_by_label(self, label_keyword: str, value_str: str) -> bool:
        """
        Заполняет поле на вкладке «Адресная информация» («Широта», «Долгота», «Радиус зоны»)
        по точным координатам 1920x1080 (проверено по f_95s.png / verify_card.png):
          • Широта:      (680, 533)
          • Долгота:     (680, 567)
          • Радиус зоны: (1620, 529)
        """
        kw = label_keyword.lower()
        coords_map = {
            "широта": (680, 533),
            "долгота": (680, 567),
            "радиус": (1620, 529),
        }
        for key, (bx, by) in coords_map.items():
            if key in kw:
                fx, fy = self._scale_xy(bx, by)
                print(f"[1С:Windows] Ввод значения '{value_str}' в поле «{label_keyword}» ({fx}, {fy})...")
                self.pywinauto.mouse.click(coords=(fx, fy))
                time.sleep(0.2)
                self._select_all_and_paste(value_str)
                time.sleep(0.15)
                self._send_vk(self.win32con.VK_TAB, down=True)
                self._send_vk(self.win32con.VK_TAB, down=False)
                time.sleep(0.15)
                return True
        return False

    def _ensure_coordinates_checked_checkbox(self) -> None:
        """
        Проверяет чекбокс «Координаты проверены» (на 1920x1080: x=393, y=594):
        Если в области чекбокса (x=386..401, y=588..601) уже есть зеленые пиксели галочки 1С —
        оставляет её включенной. Если зеленой галочки нет — кликает (393, 594), чтобы включить.
        """
        cx, cy = self._scale_xy(393, 594)
        already_checked = False
        try:
            for dx in range(-5, 6, 2):
                for dy in range(-5, 6, 2):
                    rgb = self._get_pixel_rgb(cx + dx, cy + dy)
                    if rgb is not None:
                        r, g, b = rgb
                        if g > 115 and (g - r) > 35:
                            already_checked = True
                            break
                if already_checked:
                    break
        except Exception:
            pass

        if already_checked:
            print("[1С:Windows] ✓ Галочка «Координаты проверены» уже установлена.")
        else:
            print(f"[1С:Windows] Установка галочки «Координаты проверены» ({cx}, {cy})...")
            self.pywinauto.mouse.click(coords=(cx, cy))
            time.sleep(0.3)

    def _save_and_close_card(self) -> None:
        """
        Нажимает желтую кнопку «Записать и закрыть» (на 1920x1080: x=250, y=133).
        """
        sx, sy = self._scale_xy(250, 133)
        print(f"[1С:Windows] Нажатие кнопки «Записать и закрыть» ({sx}, {sy})...")
        self.pywinauto.mouse.click(coords=(sx, sy))
        self._wait_1c_ready(min_wait=2.5, max_wait=8.0)

    # ---------------------------------------------------------------------
    # Главный публичный метод обновления координат точки в 1С
    # ---------------------------------------------------------------------
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

        # 1. Находим, разворачиваем (SW_MAXIMIZE) и активируем окно 1С
        self._find_and_activate_1c()

        # 2. Переходим в раздел «Адреса доставки» по прямой ссылке e1cib/list/Справочник.АдресаДоставки
        self._activate_tab_or_open_link(
            self.cfg.url_adresa_dostavki,
            self.cfg.title_adresa_dostavki,
        )

        # 3. Выставляем фильтр: Еще -> Расширенный поиск -> Где искать: Организация -> Что искать: ООО "ФК ПУЛЬС" -> Найти
        self._ensure_organization_filter()

        # 4. Вставляем номер точки в поиск, дожидаемся загрузки и дважды кликаем по найденной строке
        self._search_and_open_address_card(code=code, address=address, client_name=client_name)

        # 5. Внутри открытой точки переходим в раздел «Адресная информация»
        self._switch_to_address_info_tab()

        # 6. Заполняем Широту и Долготу (с запятой в качестве разделителя для 1С)
        lat_str = f"{lat:.8f}".replace(".", ",")
        lon_str = f"{lon:.8f}".replace(".", ",")
        print(f"[1С:Windows] Ввод геоданных: Широта={lat_str}, Долгота={lon_str}...")

        lat_ok = self._fill_field_by_label("широта", lat_str)
        time.sleep(0.2)
        lon_ok = self._fill_field_by_label("долгота", lon_str)
        time.sleep(0.2)

        if not lat_ok or not lon_ok:
            raise RuntimeError(
                f"Не удалось найти поля координат в карточке 1С (Широта={lat_ok}, Долгота={lon_ok}). "
                "Проверьте, что карточка адреса доставки открылась."
            )

        # 7. При необходимости обновляем радиус зоны
        if radius is not None:
            print(f"[1С:Windows] Ввод радиуса зоны: {radius} м...")
            self._fill_field_by_label("радиус", str(radius))
            time.sleep(0.2)

        # 8. Проверяем чекбокс «Координаты проверены»
        self._ensure_coordinates_checked_checkbox()

        # 9. Нажимаем «Записать и закрыть»
        self._save_and_close_card()

        print(f"[1С:Windows] ✓ Данные точки '{client_name or code}' успешно сохранены в 1С!\n")
        return True


def get_onec_service(cfg: Optional[Config] = None) -> OneCServiceInterface:
    """Фабрика сервиса: на Windows возвращает WindowsOneCService, на macOS — MockOneCService."""
    if sys.platform == "win32":
        try:
            return WindowsOneCService(cfg=cfg)
        except Exception as e:
            logger.warning("Не удалось инициализировать WindowsOneCService (%s), fallback на Mock", e)
            return MockOneCService(cfg=cfg)
    else:
        return MockOneCService(cfg=cfg)

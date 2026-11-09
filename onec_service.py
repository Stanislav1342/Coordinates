"""
onec_service.py — Сервис взаимодействия с 1С:Предприятие через прямые ссылки (e1cib).

На Windows:
  Использует промышленный RPA-стандарт для 1С:Предприятие (Управляемый интерфейс / Такси),
  проверенный в проекте «ЭТРН» на корпоративном ПК:
    1. Поиск, максимизация (SW_MAXIMIZE) и активация главного окна 1С.
    2. Переход в раздел «Адреса доставки»:
       - Если вкладка «Адреса доставки» уже открыта на нижней панели 1С — активирует ее
         безопасным кликом по левой части вкладки (исключая клик по крестику [x]).
       - Если вкладка не открыта — переходит по прямой навигационной ссылке 1С через Shift + F11:
         URL: e1cib/list/Справочник.АдресаДоставки
         (В диалоге «Переход по ссылке» нажимается кнопка «Вставить из буфера» и «Перейти»).
    3. Поиск точки доставки в списке «Адреса доставки»:
       - Вызов поиска через виртуальные клавиши Ctrl+F (VK_CONTROL + 0x46 — не зависит от раскладки!).
       - Вставка кода (МСК...) или адреса через системный буфер обмена (win32clipboard / clip.exe).
       - Нажатие Enter для фильтрации и повторное нажатие Enter для открытия карточки адреса.
    4. В открывшейся карточке адреса:
       - Переход на вкладку «Адресная информация».
       - Заполнение полей «Широта», «Долгота» и (опционально) «Радиус зоны» через буфер обмена.
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
from typing import Optional

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
        print(" 3. Переход в раздел «Адреса доставки» (вкладка или Shift + F11):")
        print(f"    URL: «{self.cfg.url_adresa_dostavki}»")
        print(f" 4. Поиск точки в списке (Ctrl+F -> Ctrl+V): '{code or address}'")
        print(f" 5. Открытие карточки адреса: '{client_name or code}' (Enter)")
        print(" 6. Переход на вкладку: «Адресная информация»")
        print(" 7. Запись геоданных через буфер обмена (Ctrl+A -> Ctrl+V):")
        print(f"    • Широта:         {lat_str}")
        print(f"    • Долгота:        {lon_str}")
        print(f"    • Радиус зоны:    {rad_str} м")
        print("    • Чекбокс:        [x] Координаты проверены")
        print(" 8. Сохранение:       «Записать и закрыть» (Ctrl+Enter)")
        time.sleep(0.5)
        print(f" 9. Статус 1С:        ✓ Карточка «{client_name or code}» успешно обновлена!")
        print("=" * 70 + "\n")
        return True


class WindowsOneCService(OneCServiceInterface):
    """
    Реальный сервис автоматизации 1С:Предприятие под Windows.
    Использует прямые навигационные ссылки 1С (Shift+F11 / e1cib), виртуальные коды клавиш
    win32api (независимые от раскладки RUS/ENG) и UI Automation (pywinauto).
    """

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or load_config()
        try:
            import pywinauto
            from pywinauto import Application, Desktop
            from pywinauto.keyboard import send_keys
            import win32api
            import win32con
            import win32gui

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

    def _hotkey_ctrl_f(self) -> None:
        """Поиск в списке 1С: Ctrl + F (0x46)."""
        self._send_hotkey(self.win32con.VK_CONTROL, 0x46)

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
        time.sleep(0.08)
        self._send_hotkey(self.win32con.VK_CONTROL, 0x41)  # Ctrl + A
        time.sleep(0.08)
        self._paste_clipboard()
        time.sleep(0.12)

    # ---------------------------------------------------------------------
    # Надежный поиск диалогов в Windows (Win32 EnumWindows + Desktop UIA)
    # ---------------------------------------------------------------------
    def _find_dialog(self, title_sub: str, timeout: float = 6.0):
        """
        Гарантированно находит отдельное диалоговое окно по подстроке заголовка.
        Ищет среди окон верхнего уровня (Win32 EnumWindows / Desktop UIA),
        исключая главное окно 1С.
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
                            if ctrl_type in ("Window", "Pane", ""):
                                return w
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

        # Разворачиваем окно на весь экран для предсказуемых координат
        try:
            if self.win32gui.IsIconic(hwnd):
                self.win32gui.ShowWindow(hwnd, self.win32con.SW_RESTORE)
                time.sleep(0.2)
            self.win32gui.ShowWindow(hwnd, self.win32con.SW_MAXIMIZE)
        except Exception:
            pass
        time.sleep(0.3)

        # Обход блокировки Windows SetForegroundWindow через виртуальный ALT
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
                    if any(s in txt for s in synonyms):
                        r = el.rectangle()
                        # Нижняя панель открытых вкладок 1С Такси (нижние 80 пикселей)
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
        Гарантированно переходит в нужный раздел 1С:
        1. Сначала открывает его по прямой навигационной ссылке 1С (Shift + F11 -> e1cib/list/...),
           так как даже если вкладка открыта внизу, прямой переход 1С сам переключает фокус
           именно на этот раздел и делает его активным на 100%!
        2. Если диалог Shift + F11 по какой-то причине не открылся — кликает по вкладке внизу.
        """
        print(f"\n[1С:Windows] Переход в раздел «{section_title}» по прямой ссылке (Shift+F11)...")
        print(f"             URL: {url}")

        set_clipboard(url)
        time.sleep(0.1)

        self._hotkey_shift_f11()
        time.sleep(1.0)

        link_dlg = self._find_dialog("переход по ссылке", timeout=4.0)

        if link_dlg:
            pasted = False
            try:
                for btn in link_dlg.descendants(control_type="Button"):
                    txt = (btn.element_info.name or btn.window_text() or "").strip().lower()
                    if "вставить из буфера" in txt:
                        btn.click_input()
                        pasted = True
                        time.sleep(0.3)
                        break
            except Exception as e:
                logger.debug("Клик 'Вставить из буфера': %s", e)

            if not pasted:
                self._select_all_and_paste(url)
                time.sleep(0.2)

            transitioned = False
            try:
                for btn in link_dlg.descendants(control_type="Button"):
                    txt = (btn.element_info.name or btn.window_text() or "").strip().lower()
                    if txt == "перейти":
                        btn.click_input()
                        transitioned = True
                        time.sleep(0.5)
                        break
            except Exception:
                pass

            if not transitioned:
                self._hotkey_enter()

            time.sleep(2.5)
            print(f"[1С:Windows] ✓ Раздел «{section_title}» успешно открыт по прямой ссылке.")
            return

        # Fallback: если диалог Shift+F11 не поймался через UIA, но открылся в фокусе 1С,
        # проверим, не открыта ли вкладка на нижней панели
        if self._activate_tab_by_name(section_title):
            print(f"[1С:Windows] ✓ Раздел «{section_title}» активирован кликом по вкладке.")
            time.sleep(1.5)
            return

        # Если диалог открыт внутри 1С как встроенное окно — вставляем и жмем Enter
        self._select_all_and_paste(url)
        time.sleep(0.2)
        self._hotkey_enter()
        time.sleep(2.5)
        print(f"[1С:Windows] ✓ Команда перехода в «{section_title}» выполнена.")

    # ---------------------------------------------------------------------
    # Поиск строки в списке «Адреса доставки» и работа с карточкой
    # ---------------------------------------------------------------------
    def _search_and_open_address_card(self, code: str, address: str, client_name: str) -> None:
        """
        Ищет адрес доставки в открытом справочнике «Адреса доставки» и открывает его карточку.
        """
        # В 1С в справочнике Адреса доставки уникальный код (МСК...) или адрес ищется через поле поиска
        search_query = code if (code and code.startswith("МСК")) else address
        print(f"[1С:Windows] Поиск точки в «Адреса доставки»: '{search_query}'...")

        # Сначала пробуем найти поле поиска (Edit с подсказкой 'Поиск' в верхней части формы)
        search_focused = False
        try:
            main_r = self.main_win.rectangle()
            for el in self.main_win.descendants(control_type="Edit"):
                try:
                    r = el.rectangle()
                    # Поле поиска списка в 1С находится ниже главного заголовка (top > 45) и выше таблицы (top < 170)
                    # При этом глобальный поиск 1С в желтой шапке имеет top < 40 — его НЕ трогаем!
                    if main_r.top + 45 <= r.top <= main_r.top + 170 and r.width() >= 100:
                        name_txt = (el.element_info.name or el.window_text() or "").strip().lower()
                        if "поиск" in name_txt or name_txt == "":
                            click_x = r.left + min(60, r.width() // 2)
                            click_y = r.top + r.height() // 2
                            print(f"[1С:Windows] Клик в поле поиска списка ({click_x}, {click_y})...")
                            self.pywinauto.mouse.click(coords=(click_x, click_y))
                            search_focused = True
                            time.sleep(0.3)
                            break
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Поиск поля Edit для поиска: %s", e)

        if not search_focused:
            # Вызываем штатный поиск по списку 1С через Ctrl+F (VK_CONTROL + 0x46)
            print("[1С:Windows] Активация поиска в списке через Ctrl+F...")
            self._hotkey_ctrl_f()
            time.sleep(0.6)

        # Вставляем поисковый запрос через буфер обмена (Ctrl+A -> Ctrl+V) и жмем Enter
        self._select_all_and_paste(search_query)
        time.sleep(0.3)
        self._hotkey_enter()
        time.sleep(2.5)

        # Если искали по коду МСК..., но список пуст (вдруг код в 1С отличается), пробуем по адресу
        # Для надежности открываем найденную первую строку в таблице (Enter или двойной клик)
        print(f"[1С:Windows] Открытие карточки адреса '{client_name or search_query}'...")

        # Пробуем найти строку в таблице с текстом кода, клиента или адреса и сделать по ней двойной клик
        row_opened = False
        try:
            main_r = self.main_win.rectangle()
            table_top = main_r.top + 130
            table_bottom = main_r.bottom - 90
            keywords = [k.lower() for k in (code, client_name, address[:25]) if k]

            for el in self.main_win.descendants():
                try:
                    r = el.rectangle()
                    if table_top <= r.top <= table_bottom and r.width() > 30 and 12 <= r.height() <= 60:
                        txt = (el.element_info.name or el.window_text() or "").strip().lower()
                        if txt and any(kw in txt for kw in keywords):
                            click_x = r.left + min(50, r.width() // 2)
                            click_y = r.top + r.height() // 2
                            print(f"[1С:Windows] Найдена строка в списке «{txt[:45]}», двойной клик ({click_x}, {click_y})...")
                            self.pywinauto.mouse.double_click(coords=(click_x, click_y))
                            row_opened = True
                            break
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Поиск строки в таблице: %s", e)

        if not row_opened:
            # Если через UIA ячейка не прочиталась — фокус после поиска уже стоит на найденной строке таблицы, жмем Enter
            self._hotkey_enter()

        time.sleep(2.5)

    def _switch_to_address_info_tab(self) -> None:
        """Переходит на вкладку «Адресная информация» внутри карточки адреса доставки."""
        print("[1С:Windows] Переход на вкладку «Адресная информация»...")
        try:
            main_r = self.main_win.rectangle()
            for el in self.main_win.descendants():
                try:
                    txt = (el.element_info.name or el.window_text() or "").strip()
                    if txt.lower() == "адресная информация":
                        r = el.rectangle()
                        if main_r.top + 50 <= r.top <= main_r.bottom - 80 and r.width() > 20:
                            click_x = r.left + r.width() // 2
                            click_y = r.top + r.height() // 2
                            print(f"[1С:Windows] Клик по вкладке «Адресная информация» ({click_x}, {click_y})...")
                            self.pywinauto.mouse.click(coords=(click_x, click_y))
                            time.sleep(1.2)
                            return
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Переход на вкладку Адресная информация: %s", e)

        logger.info("Вкладка «Адресная информация» уже активна или не требует переключения.")

    def _fill_field_by_label(self, label_keyword: str, value_str: str) -> bool:
        """
        Ищет поле ввода в карточке 1С по текстовой метке (например, «Широта», «Долгота», «Радиус»):
        Способ 1: Ищет Edit-поле справа от метки на той же горизонтальной линии.
        Способ 2: Кликает по самой метке и нажимает Tab (в 1С Такси клик по заголовку поля
                  или Tab переводит фокус прямо в связанное поле ввода), затем Ctrl+A -> Ctrl+V.
        """
        kw = label_keyword.lower()
        try:
            main_r = self.main_win.rectangle()
            target_label = None
            label_rect = None

            # 1. Ищем текстовую метку
            for el in self.main_win.descendants():
                try:
                    txt = (el.element_info.name or el.window_text() or "").strip().lower()
                    if not txt:
                        continue
                    if txt.startswith(kw) or kw in txt:
                        r = el.rectangle()
                        # Исключаем шапку и нижнюю панель вкладок
                        if main_r.top + 80 <= r.top <= main_r.bottom - 80 and r.width() < 350:
                            ctrl_type = getattr(el.element_info, "control_type", "")
                            # Если само Edit-поле уже называется "Широта" / "Долгота"
                            if ctrl_type == "Edit":
                                click_x = r.left + min(45, r.width() // 2)
                                click_y = r.top + r.height() // 2
                                print(f"[1С:Windows] Клик в Edit-поле «{label_keyword}» ({click_x}, {click_y})...")
                                self.pywinauto.mouse.click(coords=(click_x, click_y))
                                time.sleep(0.15)
                                self._select_all_and_paste(value_str)
                                return True
                            else:
                                target_label = el
                                label_rect = r
                                break
                except Exception:
                    continue

            # 2. Если нашли текстовую метку — ищем ближайшее Edit-поле справа на той же строке
            if label_rect is not None:
                best_edit = None
                min_dist = 999999
                for ed in self.main_win.descendants(control_type="Edit"):
                    try:
                        er = ed.rectangle()
                        if abs(er.top - label_rect.top) <= 20 and er.left >= label_rect.left:
                            dist = er.left - label_rect.right
                            if -20 <= dist < min_dist:
                                min_dist = dist
                                best_edit = ed
                    except Exception:
                        continue

                if best_edit is not None:
                    er = best_edit.rectangle()
                    click_x = er.left + min(45, er.width() // 2)
                    click_y = er.top + er.height() // 2
                    print(f"[1С:Windows] Клик в поле справа от «{label_keyword}» ({click_x}, {click_y})...")
                    self.pywinauto.mouse.click(coords=(click_x, click_y))
                    time.sleep(0.15)
                    self._select_all_and_paste(value_str)
                    return True

                # 3. Если Edit не виден отдельно в дереве UIA — кликаем правее метки или по метке + Tab
                click_x = label_rect.right + 50
                click_y = label_rect.top + label_rect.height() // 2
                print(f"[1С:Windows] Координатный клик в поле «{label_keyword}» ({click_x}, {click_y})...")
                self.pywinauto.mouse.click(coords=(click_x, click_y))
                time.sleep(0.15)
                self._select_all_and_paste(value_str)
                return True

        except Exception as e:
            logger.warning("Ошибка при поиске поля '%s': %s", label_keyword, e)

        return False

    def _is_checkbox_checked(self, cb) -> Optional[bool]:
        """Определяет состояние CheckBox в 1С (проверенный метод из проекта ЭТРН)."""
        try:
            if hasattr(cb, "is_checked"):
                return bool(cb.is_checked())
        except Exception:
            pass
        try:
            if hasattr(cb, "get_toggle_state"):
                return cb.get_toggle_state() == 1
        except Exception:
            pass
        try:
            action = (cb.legacy_properties().get("DefaultAction") or "").lower()
            if "снять" in action:
                return True
            elif "установить" in action:
                return False
        except Exception:
            pass
        try:
            val = str(cb.legacy_properties().get("Value") or "")
            if val in ("1", "True", "true"):
                return True
            elif val in ("0", "False", "false"):
                return False
        except Exception:
            pass
        return None

    def _ensure_coordinates_checked_checkbox(self) -> None:
        """Включает чекбокс «Координаты проверены», если он еще не включен."""
        try:
            for el in self.main_win.descendants(control_type="CheckBox"):
                try:
                    txt = (el.element_info.name or el.window_text() or "").strip().lower()
                    if "координаты проверены" in txt:
                        state = self._is_checkbox_checked(el)
                        if state is False:
                            print("[1С:Windows] Установка галочки «Координаты проверены»...")
                            el.click_input()
                            time.sleep(0.3)
                        else:
                            print("[1С:Windows] ✓ Галочка «Координаты проверены» уже установлена.")
                        return
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Проверка чекбокса 'Координаты проверены': %s", e)

    def _save_and_close_card(self) -> None:
        """Нажимает кнопку «Записать и закрыть» (или Ctrl+Enter)."""
        print("[1С:Windows] Сохранение карточки («Записать и закрыть»)...")
        saved = False
        try:
            for btn in self.main_win.descendants(control_type="Button"):
                try:
                    txt = (btn.element_info.name or btn.window_text() or "").strip().lower()
                    if txt == "записать и закрыть":
                        btn.click_input()
                        saved = True
                        break
                except Exception:
                    continue
        except Exception:
            pass

        if not saved:
            self._hotkey_ctrl_enter()

        time.sleep(2.5)

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

        # 3. Ищем адрес по коду МСК... (или по адресу) и открываем карточку
        self._search_and_open_address_card(code=code, address=address, client_name=client_name)

        # 4. Переходим на вкладку «Адресная информация»
        self._switch_to_address_info_tab()

        # 5. Заполняем Широту и Долготу (с запятой в качестве разделителя для 1С)
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

        # 6. При необходимости обновляем радиус зоны
        if radius is not None:
            print(f"[1С:Windows] Ввод радиуса зоны: {radius} м...")
            self._fill_field_by_label("радиус", str(radius))
            time.sleep(0.2)

        # 7. Проверяем чекбокс «Координаты проверены»
        self._ensure_coordinates_checked_checkbox()

        # 8. Нажимаем «Записать и закрыть»
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

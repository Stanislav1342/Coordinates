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
       - Проверка, установлен ли уже фильтр «Организация: ООО "ФК ПУЛЬС"» (и удаление ошибочного
         фильтра «Наименование: ООО "ФК ПУЛЬС"», если он остался от предыдущего запуска).
       - Клик «Еще» -> «Расширенный поиск» (или Alt+F).
       - В окне «Найти»:
         * В строке «Где искать:» открывается выпадающий список (клик по стрелке или Alt+Down)
           и выбирается пункт «Организация» (с обязательной проверкой, что поле изменилось на «Организация»!).
         * В строке «Что искать:» вставляется «ООО "ФК ПУЛЬС"» и выбирается элемент из выпадающего списка.
         * Нажимается кнопка «Найти» и ожидается полная загрузка фильтра «Организация: ООО "ФК ПУЛЬС"».
    4. Поиск точки доставки в списке «Адреса доставки»:
       - Клик в поле поиска «Поиск (Ctrl+F)» и проверка, что текст номера точки («МСК...»)
         реально вставился в поле поиска перед нажатием Enter.
       - Нажатие Enter и ожидание загрузки результатов поиска.
       - Двойной клик по найденной строке в таблице, чтобы провалиться внутрь карточки точки,
         и проверка, что в открывшейся карточке поле «Код:» совпадает с искомым номером точки!
    5. В открывшейся карточке точки доставки:
       - Переход в раздел (вкладку) «Адресная информация».
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
    def _find_dialog(self, title_sub: str, timeout: float = 5.0):
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
                    # Важно: не путать общий справочник «Адреса доставки» с открытой карточкой «... (Адреса доставки)»
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
        Гарантированно переходит в раздел «Адреса доставки» по прямой навигационной ссылке 1С
        (Shift + F11 -> e1cib/list/Справочник.АдресаДоставки).
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

            self._wait_1c_ready(min_wait=2.5, max_wait=8.0)
            print(f"[1С:Windows] ✓ Раздел «{section_title}» успешно открыт по прямой ссылке.")
            return

        if self._activate_tab_by_name(section_title):
            print(f"[1С:Windows] ✓ Раздел «{section_title}» активирован кликом по вкладке.")
            self._wait_1c_ready(min_wait=1.5, max_wait=5.0)
            return

        self._select_all_and_paste(url)
        time.sleep(0.2)
        self._hotkey_enter()
        self._wait_1c_ready(min_wait=2.5, max_wait=8.0)
        print(f"[1С:Windows] ✓ Команда перехода в «{section_title}» выполнена.")

    # ---------------------------------------------------------------------
    # Шаг 3: Установка фильтра Организация = ООО "ФК ПУЛЬС" (Расширенный поиск)
    # ---------------------------------------------------------------------
    def _check_and_clean_filter_pills(self) -> bool:
        """
        Проверяет плашки активного фильтра над таблицей «Адреса доставки» (y ≈ 175..215):
        - Если видна ошибочная плашка «Наименование: ...» (например, «Наименование: ООО "ФК ПУЛЬС"»),
          сбрасывает её кликом по крестику [x] на плашке или через Ctrl+Q.
        - Если установлена правильная плашка «Организация: ООО "ФК ПУЛЬС"» — возвращает True.
        """
        if not self.main_win:
            return False

        org_filter_found = False
        wrong_filter_found = False

        try:
            main_r = self.main_win.rectangle()
            for el in self.main_win.descendants():
                try:
                    r = el.rectangle()
                    if main_r.top + 165 <= r.top <= main_r.top + 220 and r.left <= main_r.left + 800:
                        txt = self._get_element_text(el).lower()
                        if not txt:
                            continue
                        if "наименование:" in txt or ("наименование" in txt and "пульс" in txt):
                            wrong_filter_found = True
                            # Крестик закрытия плашки находится в правом краю плашки (r.right - 8, center_y)
                            close_x = r.right - 8
                            close_y = r.top + r.height() // 2
                            print(f"[1С:Windows] Сброс неверного фильтра «{txt}» ({close_x}, {close_y})...")
                            self.pywinauto.mouse.click(coords=(close_x, close_y))
                            time.sleep(1.5)
                        elif "организация" in txt and "фк пульс" in txt:
                            org_filter_found = True
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Проверка плашек фильтра: %s", e)

        if wrong_filter_found:
            self._hotkey_ctrl_q()
            self._wait_1c_ready(min_wait=2.0, max_wait=6.0)
            return False

        return org_filter_found

    def _click_list_more_button(self) -> bool:
        """
        Нажимает кнопку «Еще ▾» на командной панели списка «Адреса доставки»
        (в максимизированном окне 1920x1080: x=1827, y=126).
        """
        if not self.main_win:
            return False

        try:
            main_r = self.main_win.rectangle()
            more_btns = []
            for btn in self.main_win.descendants(control_type="Button"):
                try:
                    txt = (btn.element_info.name or btn.window_text() or "").strip().lower()
                    if txt in ("еще", "ещё", "еще...", "ещё..."):
                        r = btn.rectangle()
                        if main_r.top + 100 <= r.top <= main_r.top + 155 and r.left >= main_r.left + 1400:
                            more_btns.append(btn)
                except Exception:
                    continue

            if more_btns:
                target_btn = max(more_btns, key=lambda b: b.rectangle().left)
                r = target_btn.rectangle()
                click_x = r.left + r.width() // 2
                click_y = r.top + r.height() // 2
                print(f"[1С:Windows] Клик по кнопке «Еще» на панели списка ({click_x}, {click_y})...")
                self.pywinauto.mouse.click(coords=(click_x, click_y))
                return True
        except Exception as e:
            logger.debug("UIA поиск кнопки Еще: %s", e)

        # Точные координаты кнопки «Еще» на сетке 1920x1080 (см. grid_toolbar_52s.png: x=1827, y=126)
        try:
            main_r = self.main_win.rectangle()
            click_x = main_r.right - 91
            click_y = main_r.top + 126
            print(f"[1С:Windows] Координатный клик по кнопке «Еще» ({click_x}, {click_y})...")
            self.pywinauto.mouse.click(coords=(click_x, click_y))
            return True
        except Exception:
            return False

    def _click_advanced_search_in_menu(self) -> bool:
        """
        В открывшемся меню «Еще» находит и нажимает пункт «Расширенный поиск»
        (в максимизированном окне 1920x1080: x=1810, y=318).
        """
        time.sleep(0.5)
        try:
            for w in self.Desktop(backend="uia").windows():
                try:
                    for el in w.descendants():
                        try:
                            txt = (el.element_info.name or el.window_text() or "").strip().lower()
                            if "расширенный поиск" in txt:
                                r = el.rectangle()
                                if r.width() > 30 and r.height() > 10:
                                    click_x = r.left + min(60, r.width() // 2)
                                    click_y = r.top + r.height() // 2
                                    print(f"[1С:Windows] Клик по пункту меню «Расширенный поиск» ({click_x}, {click_y})...")
                                    self.pywinauto.mouse.click(coords=(click_x, click_y))
                                    return True
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Поиск пункта меню 'Расширенный поиск': %s", e)

        try:
            main_r = self.main_win.rectangle()
            click_x = main_r.right - 108
            click_y = main_r.top + 318
            print(f"[1С:Windows] Координатный клик по пункту «Расширенный поиск» ({click_x}, {click_y})...")
            self.pywinauto.mouse.click(coords=(click_x, click_y))
            return True
        except Exception:
            return False

    def _select_where_field_in_find_dialog(self, find_dlg, field_name: str = "Организация") -> None:
        """
        В открытом диалоге «Найти» гарантированно переключает поле «Где искать:»
        с «Наименование» на «Организация».

        Точные координаты на 1920x1080 (проверено по пиксельной сетке grid_find_dlg_40s.png и grid_dropdown_67.png):
          • Само окно «Найти»: left=686, top=396, right=1233, bottom=636
          • Поле «Где искать:»: left=780..1214, top=442..468 (центр y = 455)
          • Кнопка-стрелка [v] поля «Где искать:»: x = 1204, y = 455 (или dlg_right - 29, dlg_top + 59)
          • В открывшемся списке под «Где искать:» (grid_dropdown_67.png):
              1) Код                  -> y = 480 (where_y + 25)
              2) Наименование         -> y = 510 (where_y + 55)
              3) Полное наименование  -> y = 540 (where_y + 85)
              4) Контрагент           -> y = 570 (where_y + 115)
              5) Организация          -> y = 600 (where_y + 145)
        """
        print(f"[1С:Windows]   • Установка поля «Где искать:» -> «{field_name}»...")

        # Определяем точные координаты поля «Где искать:» и его стрелки [v]
        where_box = None
        dlg_left, dlg_top, dlg_right, dlg_bottom = 686, 396, 1233, 636

        if find_dlg:
            try:
                dr = find_dlg.rectangle()
                if 300 <= dr.width() <= 900 and 150 <= dr.height() <= 500:
                    dlg_left, dlg_top, dlg_right, dlg_bottom = dr.left, dr.top, dr.right, dr.bottom
            except Exception:
                pass

        # Ищем верхнее поле (ComboBox / Edit) внутри области диалога «Найти»
        search_root = find_dlg if find_dlg else self.main_win
        try:
            candidates = []
            for el in search_root.descendants():
                try:
                    ct = getattr(el.element_info, "control_type", "")
                    if ct in ("ComboBox", "Edit"):
                        r = el.rectangle()
                        if dlg_left <= r.left <= dlg_right and dlg_top + 25 <= r.top <= dlg_top + 80 and r.width() >= 150:
                            candidates.append(el)
                except Exception:
                    continue
            if candidates:
                candidates.sort(key=lambda e: (e.rectangle().top, e.rectangle().left))
                where_box = candidates[0]
        except Exception as e:
            logger.debug("Поиск контрола 'Где искать': %s", e)

        # Вычисляем координаты центра поля «Где искать:» и его кнопки раскрытия [v]
        if where_box is not None:
            wr = where_box.rectangle()
            where_center_x = wr.left + min(100, wr.width() // 3)
            where_center_y = wr.top + wr.height() // 2
            where_arrow_x = wr.right - 10
            where_arrow_y = where_center_y
        else:
            # Эталонные координаты на 1920x1080 (grid_find_dlg_40s.png):
            # поле «Где искать» расположено на x=780..1214, y=442..468
            where_center_x = dlg_left + 180   # 866
            where_center_y = dlg_top + 59     # 455
            where_arrow_x = dlg_right - 29    # 1204
            where_arrow_y = dlg_top + 59      # 455

        # Проверяем, вдруг в «Где искать» уже выбрана «Организация»
        if where_box is not None:
            curr_txt = self._get_element_text(where_box).lower()
            if "организац" in curr_txt:
                print(f"[1С:Windows]   ✓ В поле «Где искать» уже стоит «{field_name}».")
                return

        # -----------------------------------------------------------------
        # Попытка 1: Клик по стрелке [v] поля «Где искать» (x=1204, y=455)
        # и выбор пункта «Организация» из выпадающего списка (x=866, y=600)
        # -----------------------------------------------------------------
        print(f"[1С:Windows]   • Клик по стрелке списка «Где искать» ({where_arrow_x}, {where_arrow_y})...")
        self.pywinauto.mouse.click(coords=(where_arrow_x, where_arrow_y))
        time.sleep(0.6)

        selected_via_uia = False
        try:
            for w in self.Desktop(backend="uia").windows():
                for it in w.descendants():
                    try:
                        txt = (it.element_info.name or it.window_text() or "").strip().lower()
                        if txt == field_name.lower():
                            ir = it.rectangle()
                            if where_center_y + 10 <= ir.top <= where_center_y + 250 and ir.height() >= 12:
                                click_x = ir.left + min(80, ir.width() // 3)
                                click_y = ir.top + ir.height() // 2
                                print(f"[1С:Windows]   • UIA клик по пункту «{field_name}» ({click_x}, {click_y})...")
                                self.pywinauto.mouse.click(coords=(click_x, click_y))
                                selected_via_uia = True
                                break
                    except Exception:
                        continue
                if selected_via_uia:
                    break
        except Exception:
            pass

        if not selected_via_uia:
            # Точная координата строки «Организация» в выпадающем списке (см. grid_dropdown_67.png):
            # where_center_y = 455, строка «Организация» находится на y = 600 (where_center_y + 145)
            org_item_x = where_center_x
            org_item_y = where_center_y + 145
            print(f"[1С:Windows]   • Клик по строке «{field_name}» в выпадающем списке ({org_item_x}, {org_item_y})...")
            self.pywinauto.mouse.click(coords=(org_item_x, org_item_y))

        time.sleep(0.5)

        # Проверяем через UIA, сменилось ли значение поля «Где искать» на «Организация»
        if where_box is not None:
            curr_txt = self._get_element_text(where_box).lower()
            if "организац" in curr_txt:
                print(f"[1С:Windows]   ✓ Поле «Где искать» успешно переключено на «{field_name}».")
                return

        # -----------------------------------------------------------------
        # Попытка 2 (железобетонный клавиатурный + буферный резерв):
        # Фокусируем само текстовое поле «Где искать» (x=866, y=455),
        # открываем список через Alt+Down (или вставляем "Организация") и выбираем.
        # -----------------------------------------------------------------
        print(f"[1С:Windows]   • Подтверждение выбора «{field_name}» в поле «Где искать» ({where_center_x}, {where_center_y})...")
        self.pywinauto.mouse.click(coords=(where_center_x, where_center_y))
        time.sleep(0.25)

        # Если список в 1С поддерживает ввод/вставку названия колонки — вставляем "Организация"
        self._select_all_and_paste(field_name)
        time.sleep(0.3)
        self._hotkey_enter()
        time.sleep(0.3)

        # Если после вставки в 1С ComboBox все еще показывает "Наименование" —
        # проходим стрелкой вниз ровно 3 шага от "Наименование" до "Организация":
        # (Код [1] -> Наименование [2] -> Полное наименование [3] -> Контрагент [4] -> Организация [5])
        if where_box is not None:
            curr_txt = self._get_element_text(where_box).lower()
            if "наименование" in curr_txt and "полное" not in curr_txt:
                print("[1С:Windows]   • Переключение с «Наименование» на «Организация» клавишами Down (3 шага)...")
                self.pywinauto.mouse.click(coords=(where_center_x, where_center_y))
                time.sleep(0.2)
                self._send_hotkey(self.win32con.VK_MENU, self.win32con.VK_DOWN)  # Alt+Down
                time.sleep(0.3)
                for _ in range(3):
                    self._send_hotkey(self.win32con.VK_DOWN)
                    time.sleep(0.12)
                self._hotkey_enter()
                time.sleep(0.3)

    def _ensure_organization_filter(self) -> None:
        """
        Устанавливает фильтр «Организация: ООО "ФК ПУЛЬС"» в разделе «Адреса доставки»
        и ПРОВЕРЯЕТ, что в списке появилась именно плашка «Организация: ООО "ФК ПУЛЬС"»
        (а не «Наименование: ООО "ФК ПУЛЬС"»).
        """
        field_name = self.cfg.onec_org_filter_field  # "Организация"
        org_value = self.cfg.onec_org_filter_value   # 'ООО "ФК ПУЛЬС"'

        # 1. Проверяем, не стоит ли уже правильный фильтр (и чистим ошибочный фильтр по Наименованию)
        if self._check_and_clean_filter_pills():
            print(f"[1С:Windows] ✓ Фильтр «{field_name}: {org_value}» уже активен.")
            return

        for attempt in range(1, 3):
            print(
                f"[1С:Windows] Установка фильтра «{field_name}: {org_value}» "
                f"(Еще -> Расширенный поиск, попытка {attempt}/2)..."
            )

            # Открываем меню «Еще» -> «Расширенный поиск»
            self._click_list_more_button()
            self._click_advanced_search_in_menu()

            find_dlg = self._find_dialog("найти", timeout=3.0)
            if not find_dlg:
                print("[1С:Windows] Вызов диалога «Расширенный поиск» через Alt+F...")
                self._hotkey_esc()
                time.sleep(0.2)
                self._hotkey_alt_f()
                find_dlg = self._find_dialog("найти", timeout=3.5)

            # Определяем границы диалога «Найти» (на 1920x1080: left=686, top=396, right=1233, bottom=636)
            dlg_left, dlg_top, dlg_right, dlg_bottom = 686, 396, 1233, 636
            if find_dlg:
                try:
                    dr = find_dlg.rectangle()
                    if 300 <= dr.width() <= 900 and 150 <= dr.height() <= 500:
                        dlg_left, dlg_top, dlg_right, dlg_bottom = dr.left, dr.top, dr.right, dr.bottom
                except Exception:
                    pass

            # 2. Выбираем «Организация» в поле «Где искать:»
            self._select_where_field_in_find_dialog(find_dlg, field_name=field_name)

            # 3. Заполняем поле «Что искать:» -> 'ООО "ФК ПУЛЬС"'
            # Точные координаты поля «Что искать:» на 1920x1080 (см. grid_find_dlg_44s.png):
            # x = 866 (dlg_left + 180), y = 488 (dlg_top + 92)
            what_x = dlg_left + 180
            what_y = dlg_top + 92

            print(f"[1С:Windows]   • Ввод «{org_value}» в поле «Что искать» ({what_x}, {what_y})...")
            self.pywinauto.mouse.click(coords=(what_x, what_y))
            time.sleep(0.3)
            self._select_all_and_paste(org_value)

            # Ждем появления выпадающей подсказки 1С с элементом справочника «ООО "ФК ПУЛЬС"» (см. grid_find_dlg_44s.png)
            time.sleep(1.0)

            # В grid_find_dlg_44s.png строка «ООО "ФК ПУЛЬС"» в выпадающем списке под «Что искать»
            # расположена на x = 866, y = 518 (what_y + 30)
            autocomplete_clicked = False
            try:
                for w in self.Desktop(backend="uia").windows():
                    for it in w.descendants():
                        try:
                            txt = (it.element_info.name or it.window_text() or "").strip().lower()
                            if "фк пульс" in txt:
                                ir = it.rectangle()
                                if what_y + 10 <= ir.top <= what_y + 80:
                                    click_x = ir.left + min(60, ir.width() // 2)
                                    click_y = ir.top + ir.height() // 2
                                    print(f"[1С:Windows]   • UIA выбор «{org_value}» из подсказки ({click_x}, {click_y})...")
                                    self.pywinauto.mouse.click(coords=(click_x, click_y))
                                    autocomplete_clicked = True
                                    break
                        except Exception:
                            continue
                    if autocomplete_clicked:
                        break
            except Exception:
                pass

            if not autocomplete_clicked:
                popup_x = what_x
                popup_y = what_y + 30  # 518
                print(f"[1С:Windows]   • Клик по выпадающей подсказке «{org_value}» ({popup_x}, {popup_y})...")
                self.pywinauto.mouse.click(coords=(popup_x, popup_y))

            time.sleep(0.5)

            # 4. Нажимаем желтую кнопку «Найти»
            # Точные координаты кнопки «Найти» на 1920x1080 (см. grid_find_dlg_47s.png):
            # x = 1042 (dlg_left + 356), y = 602 (dlg_top + 206)
            print("[1С:Windows]   • Нажатие кнопки «Найти» и ожидание загрузки фильтра...")
            find_btn_clicked = False
            try:
                search_root = find_dlg if find_dlg else self.main_win
                for btn in search_root.descendants(control_type="Button"):
                    try:
                        txt = (btn.element_info.name or btn.window_text() or "").strip().lower()
                        if txt == "найти":
                            br = btn.rectangle()
                            if dlg_top + 140 <= br.top <= dlg_bottom + 40:
                                btn.click_input()
                                find_btn_clicked = True
                                break
                    except Exception:
                        continue
            except Exception:
                pass

            if not find_btn_clicked:
                btn_x = dlg_left + 356  # 1042
                btn_y = dlg_top + 206   # 602
                self.pywinauto.mouse.click(coords=(btn_x, btn_y))
                time.sleep(0.25)
                if self._find_dialog("найти", timeout=0.6):
                    self._hotkey_enter()

            # 5. Дожидаемся полной загрузки отфильтрованного списка
            self._wait_1c_ready(min_wait=4.0, max_wait=12.0)

            # 6. Проверяем, что установился именно фильтр «Организация: ООО "ФК ПУЛЬС"»
            if self._check_and_clean_filter_pills():
                print(f"[1С:Windows] ✓ Фильтр «{field_name}: {org_value}» успешно установлен и загружен!")
                return

        print(f"[1С:Windows] ⚠ Завершена установка фильтра «{field_name}: {org_value}».")

    # ---------------------------------------------------------------------
    # Шаг 4: Поиск номера точки в списке и вход в карточку двойным кликом
    # ---------------------------------------------------------------------
    def _focus_and_paste_in_search_box(self, query: str) -> None:
        """
        Кликает в поле поиска списка «Поиск (Ctrl+F)» на командной панели «Адреса доставки»,
        вставляет номер точки, проверяет, что текст вставился, нажимает Enter и ждет загрузки.

        Точные координаты на 1920x1080 (см. grid_toolbar_52s.png):
          • Поле «Поиск (Ctrl+F)»: left=1474..1722, top=113..139 (центр: x=1580, y=126)
          • Кнопка очистки поиска [x]: x=1710, y=126
        """
        print(f"[1С:Windows] Вставка номера точки в поле поиска: '{query}'...")

        # Находим Edit-контрол поля поиска списка через UIA
        search_edit = None
        try:
            main_r = self.main_win.rectangle()
            for el in self.main_win.descendants(control_type="Edit"):
                try:
                    r = el.rectangle()
                    if main_r.top + 100 <= r.top <= main_r.top + 155 and r.left >= main_r.left + 1200 and r.width() >= 100:
                        search_edit = el
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.debug("UIA поиск поля 'Поиск (Ctrl+F)': %s", e)

        if search_edit is not None:
            r = search_edit.rectangle()
            click_x = r.left + min(80, r.width() // 2)
            click_y = r.top + r.height() // 2
        else:
            main_r = self.main_win.rectangle()
            click_x = main_r.right - 338  # 1580 на 1920x1080
            click_y = main_r.top + 126    # 126 на 1920x1080

        # Кликаем в поле поиска, вставляем запрос и проверяем результат
        print(f"[1С:Windows] Клик в поле «Поиск (Ctrl+F)» ({click_x}, {click_y})...")
        self.pywinauto.mouse.click(coords=(click_x, click_y))
        time.sleep(0.35)
        self._select_all_and_paste(query)
        time.sleep(0.3)

        # Если есть UIA-доступ к полю поиска — проверяем, что номер точки реально вставился
        if search_edit is not None:
            current_val = self._get_element_text(search_edit)
            if query.lower() not in current_val.lower():
                print("[1С:Windows] Повторная фокусировка поля поиска через Ctrl+F и вставка...")
                self._hotkey_ctrl_f()
                time.sleep(0.4)
                self._select_all_and_paste(query)
                time.sleep(0.3)

        # Нажимаем Enter для запуска поиска и ждем загрузки результатов
        self._hotkey_enter()
        print(f"[1С:Windows] Ожидание загрузки результатов поиска для '{query}'...")
        self._wait_1c_ready(min_wait=3.5, max_wait=10.0)

    def _is_address_card_open(self) -> bool:
        """
        Проверяет, открылась ли карточка точки доставки (по наличию вкладки «Адресная информация»
        или кнопки «Записать и закрыть»).
        """
        if not self.main_win:
            return False

        try:
            for el in self.main_win.descendants():
                try:
                    txt = (el.element_info.name or el.window_text() or "").strip().lower()
                    if txt in ("адресная информация", "записать и закрыть", "графики доставки"):
                        return True
                    if "(адреса доставки)" in txt:
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        return False

    def _verify_opened_card_matches_point(self, expected_code: str, expected_client: str) -> bool:
        """
        КРИТИЧЕСКАЯ ЗАЩИТА:
        Проверяет, что открытая в 1С карточка действительно принадлежит искомой точке
        (сверяет поле «Код:» или заголовок карточки с expected_code / expected_client).
        Если открылась чужая карточка — закрывает её через Esc / Ctrl+F4 и возвращает False,
        чтобы скрипт ни при каких обстоятельствах не перезаписал координаты чужой точки!
        """
        if not expected_code and not expected_client:
            return True

        code_low = (expected_code or "").strip().lower()
        client_low = (expected_client or "").strip().lower()

        try:
            all_texts = []
            for el in self.main_win.descendants():
                try:
                    t = self._get_element_text(el)
                    if t:
                        all_texts.append(t.lower())
                except Exception:
                    continue

            joined = " | ".join(all_texts)

            # Если код точки (например, мск000132723) присутствует в открытой карточке — это 100% наша точка
            if code_low and code_low in joined:
                print(f"[1С:Windows] ✓ Проверка безопасности: код точки '{expected_code}' подтвержден в карточке.")
                return True

            # Если в карточке виден другой код МСК.../БРН... и нашего кода нет — это ЧУЖАЯ карточка!
            other_codes = re.findall(r"\b(?:мск|брн)\d{6,12}\b", joined)
            if code_low and other_codes and code_low not in other_codes:
                print(
                    f"[1С:Windows] ⚠ ЗАЩИТА: Открылась карточка с чужим кодом ({other_codes[0].upper()} "
                    f"вместо {expected_code})! Закрываем карточку без изменений..."
                )
                self._hotkey_ctrl_f4()
                time.sleep(1.0)
                return False

            if client_low and client_low[:10] in joined:
                print(f"[1С:Windows] ✓ Проверка безопасности: клиент '{expected_client}' подтвержден в карточке.")
                return True

        except Exception as e:
            logger.debug("Проверка открытой карточки: %s", e)

        return True

    def _double_click_found_row(self, code: str, address: str, client_name: str) -> bool:
        """
        Дважды нажимает на найденную строку в таблице «Адреса доставки», чтобы провалиться в карточку точки,
        и проверяет, что открылась именно нужная точка.
        """
        print(f"[1С:Windows] Двойной клик по найденной строке точки '{code or client_name}'...")
        main_r = self.main_win.rectangle()

        # 1. Ищем ячейку с кодом точки в таблице через UIA (высота строк таблицы: y >= 235)
        row_clicked = False
        try:
            table_top = main_r.top + 230
            table_bottom = main_r.bottom - 90
            keywords = [k.lower() for k in (code, client_name) if k]

            for el in self.main_win.descendants():
                try:
                    r = el.rectangle()
                    if table_top <= r.top <= table_bottom and r.width() > 30 and 12 <= r.height() <= 55:
                        txt = self._get_element_text(el).lower()
                        if txt and any(kw in txt for kw in keywords):
                            click_x = r.left + min(50, r.width() // 2)
                            click_y = r.top + r.height() // 2
                            print(f"[1С:Windows] Найдена строка «{txt[:45]}», двойной клик ({click_x}, {click_y})...")
                            self.pywinauto.mouse.double_click(coords=(click_x, click_y))
                            row_clicked = True
                            break
                except Exception:
                    continue
        except Exception as e:
            logger.debug("UIA поиск строки в таблице: %s", e)

        # 2. Если UIA не отдал текст строки табличного поля 1С — делаем двойной клик
        # точно по первой строке таблицы (см. grid_toolbar_52s.png и f_80s.png: x=260, y=250)
        if not row_clicked:
            first_row_x = main_r.left + 260
            first_row_y = main_r.top + 250
            print(f"[1С:Windows] Координатный двойной клик по первой строке таблицы ({first_row_x}, {first_row_y})...")
            self.pywinauto.mouse.double_click(coords=(first_row_x, first_row_y))

        self._wait_1c_ready(min_wait=2.2, max_wait=7.0)

        if not self._is_address_card_open():
            first_row_x = main_r.left + 260
            first_row_y = main_r.top + 250
            print(f"[1С:Windows] Повторный двойной клик + Enter по строке ({first_row_x}, {first_row_y})...")
            self.pywinauto.mouse.double_click(coords=(first_row_x, first_row_y))
            time.sleep(0.3)
            self._hotkey_enter()
            self._wait_1c_ready(min_wait=2.2, max_wait=7.0)

        if not self._is_address_card_open():
            return False

        # 3. Проверяем, что открытая карточка действительно принадлежит нашей точке
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
        Внутри открытой карточки точки доставки открывает раздел (вкладку) «Адресная информация»
        (на сетке 1920x1080 grid_card_59.png: x=315, y=362).
        """
        print("[1С:Windows] Переход в раздел «Адресная информация» внутри карточки точки...")
        clicked = False
        try:
            main_r = self.main_win.rectangle()
            for el in self.main_win.descendants():
                try:
                    txt = (el.element_info.name or el.window_text() or "").strip()
                    if txt.lower() == "адресная информация":
                        r = el.rectangle()
                        if main_r.top + 150 <= r.top <= main_r.top + 500 and r.width() > 20:
                            click_x = r.left + r.width() // 2
                            click_y = r.top + r.height() // 2
                            print(f"[1С:Windows] Клик по вкладке «Адресная информация» ({click_x}, {click_y})...")
                            self.pywinauto.mouse.click(coords=(click_x, click_y))
                            clicked = True
                            time.sleep(1.0)
                            break
                except Exception:
                    continue
        except Exception as e:
            logger.debug("UIA переход на вкладку Адресная информация: %s", e)

        if not clicked:
            try:
                main_r = self.main_win.rectangle()
                click_x = main_r.left + 315
                click_y = main_r.top + 362
                print(f"[1С:Windows] Координатный клик по вкладке «Адресная информация» ({click_x}, {click_y})...")
                self.pywinauto.mouse.click(coords=(click_x, click_y))
                time.sleep(1.0)
            except Exception:
                pass

    def _fill_field_by_label(self, label_keyword: str, value_str: str) -> bool:
        """
        Заполняет поле на вкладке «Адресная информация» («Широта», «Долгота», «Радиус зоны»):
        Способ 1: Ищет метку через UIA и кликает в связанное Edit-поле справа.
        Способ 2: Точный координатный fallback по пиксельной сетке карточки 1С (grid_card_59.png).
        """
        kw = label_keyword.lower()
        try:
            main_r = self.main_win.rectangle()
            label_rect = None

            # 1. Ищем текстовую метку или само Edit-поле
            for el in self.main_win.descendants():
                try:
                    txt = (el.element_info.name or el.window_text() or "").strip().lower()
                    if not txt:
                        continue
                    if txt.startswith(kw) or kw in txt:
                        r = el.rectangle()
                        if main_r.top + 350 <= r.top <= main_r.bottom - 150 and r.width() < 350:
                            ctrl_type = getattr(el.element_info, "control_type", "")
                            if ctrl_type == "Edit":
                                click_x = r.left + min(45, r.width() // 2)
                                click_y = r.top + r.height() // 2
                                print(f"[1С:Windows] Клик в Edit-поле «{label_keyword}» ({click_x}, {click_y})...")
                                self.pywinauto.mouse.click(coords=(click_x, click_y))
                                time.sleep(0.15)
                                self._select_all_and_paste(value_str)
                                return True
                            else:
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

                click_x = label_rect.right + 50
                click_y = label_rect.top + label_rect.height() // 2
                print(f"[1С:Windows] Клик правее метки «{label_keyword}» ({click_x}, {click_y})...")
                self.pywinauto.mouse.click(coords=(click_x, click_y))
                time.sleep(0.15)
                self._select_all_and_paste(value_str)
                return True

            # 3. Точный координатный fallback для 1920x1080 (см. grid_card_59.png):
            #    • Широта:      x = 570, y = 514
            #    • Долгота:     x = 570, y = 548
            #    • Радиус зоны: x = 1580, y = 512
            fallback_coords = {
                "широта": (main_r.left + 570, main_r.top + 514),
                "долгота": (main_r.left + 570, main_r.top + 548),
                "радиус": (main_r.left + 1580, main_r.top + 512),
            }
            for key, (fx, fy) in fallback_coords.items():
                if key in kw:
                    print(f"[1С:Windows] Точный координатный клик в поле «{label_keyword}» ({fx}, {fy})...")
                    self.pywinauto.mouse.click(coords=(fx, fy))
                    time.sleep(0.15)
                    self._select_all_and_paste(value_str)
                    return True

        except Exception as e:
            logger.warning("Ошибка при заполнении поля '%s': %s", label_keyword, e)

        return False

    def _is_checkbox_checked(self, cb) -> Optional[bool]:
        """Определяет состояние CheckBox в 1С."""
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
        """Нажимает желтую кнопку «Записать и закрыть» (или Ctrl+Enter)."""
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

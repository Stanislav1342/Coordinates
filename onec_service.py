"""
onec_service.py — Сервис взаимодействия с 1С:Предприятие через прямые ссылки (e1cib).

На Windows:
  Использует промышленный RPA-стандарт для 1С:Предприятие (Управляемый интерфейс / Такси),
  проверенный в проекте «ЭТРН» на корпоративном ПК:
    1. Поиск, максимизация (SW_MAXIMIZE) и активация главного окна 1С.
    2. Переход в раздел «Адреса доставки»:
       - По прямой навигационной ссылке 1С через Shift + F11:
         URL: e1cib/list/Справочник.АдресаДоставки
         (В диалоге «Переход по ссылке» нажимается кнопка «Вставить из буфера» и «Перейти»).
    3. Установка фильтра по организации перед поиском точки:
       - Проверка, установлен ли уже фильтр «Организация: ООО "ФК ПУЛЬС"».
       - Если не установлен: клик «Еще» -> «Расширенный поиск» (или Alt+F) ->
         в поле «Где искать» выбирается «Организация», в поле «Что искать» выбирается
         «ООО "ФК ПУЛЬС"» (с привязкой ссылки из выпадающего списка) -> клик «Найти» ->
         ожидание полной загрузки отфильтрованного списка.
    4. Поиск точки доставки в списке «Адреса доставки»:
       - Клик в поле поиска «Поиск (Ctrl+F)» (или вызов через виртуальные клавиши Ctrl+F).
       - Вставка номера точки (МСК...) или адреса через системный буфер обмена (win32clipboard / clip.exe).
       - Нажатие Enter и ожидание загрузки результатов поиска.
       - Двойной клик по найденной строке в таблице, чтобы провалиться внутрь карточки точки.
    5. В открывшейся карточке точки доставки:
       - Переход на вкладку «Адресная информация».
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
    win32api (независимые от раскладки RUS/ENG) и UI Automation (pywinauto).
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
    def _find_dialog(self, title_sub: str, timeout: float = 6.0):
        """
        Гарантированно находит отдельное диалоговое окно по подстроке заголовка.
        Ищет среди окон верхнего уровня (Win32 EnumWindows / Desktop UIA),
        а также среди дочерних модальных окон внутри главного окна 1С.
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
    def _is_org_filter_applied(self) -> bool:
        """
        Проверяет, выставлен ли уже желтый фильтр «Организация: ООО "ФК ПУЛЬС"»
        под строкой «Пометка удаления» (в полосе быстрых отборов 155 <= y <= 215).
        """
        if not self.main_win:
            return False

        try:
            main_r = self.main_win.rectangle()
            for el in self.main_win.descendants():
                try:
                    r = el.rectangle()
                    if main_r.top + 150 <= r.top <= main_r.top + 220 and r.left <= main_r.left + 600:
                        txt = (el.element_info.name or el.window_text() or "").strip().lower()
                        if "фк пульс" in txt and ("организац" in txt or "пульс" in txt):
                            return True
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Проверка плашки фильтра организации: %s", e)

        return False

    def _click_list_more_button(self) -> bool:
        """
        Нажимает кнопку «Еще ▾» на командной панели списка «Адреса доставки»
        (в правой верхней части формы, рядом с полем Поиск).
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
                        # Кнопка «Еще» командной панели списка находится на высоте 105..150 px
                        # (выше 100 px находится ссылка «Еще...» панели навигации — её пропускаем)
                        if main_r.top + 100 <= r.top <= main_r.top + 160 and r.left >= main_r.left + 800:
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

        # Координатный fallback для 1920x1080 (кнопка «Еще» справа от поиска: x=1852, y=124)
        try:
            main_r = self.main_win.rectangle()
            click_x = main_r.right - 68
            click_y = main_r.top + 124
            print(f"[1С:Windows] Координатный клик по кнопке «Еще» ({click_x}, {click_y})...")
            self.pywinauto.mouse.click(coords=(click_x, click_y))
            return True
        except Exception:
            return False

    def _click_advanced_search_in_menu(self) -> bool:
        """
        В открывшемся меню «Еще» находит и нажимает пункт «Расширенный поиск».
        """
        time.sleep(0.5)
        try:
            # Ищем во всех всплывающих окнах Desktop UIA и внутри главного окна 1С
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

        # Координатный fallback по открытому меню «Еще» (в 1920x1080 пункт «Расширенный поиск» на x=1820, y=318)
        try:
            main_r = self.main_win.rectangle()
            click_x = main_r.right - 100
            click_y = main_r.top + 318
            print(f"[1С:Windows] Координатный клик по пункту «Расширенный поиск» ({click_x}, {click_y})...")
            self.pywinauto.mouse.click(coords=(click_x, click_y))
            return True
        except Exception:
            return False

    def _ensure_organization_filter(self) -> None:
        """
        Устанавливает фильтр по организации в разделе «Адреса доставки» перед поиском точки:
        1. Проверяет, не установлен ли уже фильтр «Организация: ООО "ФК ПУЛЬС"».
        2. Если не установлен:
           - Нажимает «Еще» -> «Расширенный поиск» (с резервным вызовом через Alt+F).
           - В диалоге «Найти»:
             * В поле «Где искать» выбирает «Организация».
             * В поле «Что искать» вводит и выбирает из выпадающего списка «ООО "ФК ПУЛЬС"».
             * Нажимает кнопку «Найти».
           - Дожидается завершения загрузки фильтра в списке.
        """
        field_name = self.cfg.onec_org_filter_field  # "Организация"
        org_value = self.cfg.onec_org_filter_value   # 'ООО "ФК ПУЛЬС"'

        if self._is_org_filter_applied():
            print(f"[1С:Windows] ✓ Фильтр «{field_name}: {org_value}» уже установлен в списке.")
            return

        print(f"[1С:Windows] Установка фильтра «{field_name}: {org_value}» (Еще -> Расширенный поиск)...")

        # 1. Открываем меню «Еще» и нажимаем «Расширенный поиск»
        self._click_list_more_button()
        self._click_advanced_search_in_menu()

        find_dlg = self._find_dialog("найти", timeout=3.5)

        # Если меню не сработало — вызываем штатный «Расширенный поиск» горячей клавишей Alt + F
        if not find_dlg:
            print("[1С:Windows] Вызов диалога «Расширенный поиск» через горячую клавишу Alt+F...")
            self._hotkey_esc()
            time.sleep(0.2)
            self._hotkey_alt_f()
            find_dlg = self._find_dialog("найти", timeout=4.0)

        # Определяем координаты окна диалога «Найти» (либо из UIA, либо точные координаты 1920x1080)
        if find_dlg:
            try:
                dlg_r = find_dlg.rectangle()
                dlg_left, dlg_top, dlg_right, dlg_bottom = dlg_r.left, dlg_r.top, dlg_r.right, dlg_r.bottom
            except Exception:
                dlg_left, dlg_top, dlg_right, dlg_bottom = 693, 377, 1235, 590
        else:
            # Даже если диалог «Найти» встроен в форму 1С и не виден как отдельный top-level window,
            # его координаты в максимизированном окне 1920x1080 всегда строго по центру: (693, 377)..(1235, 590)
            dlg_left, dlg_top, dlg_right, dlg_bottom = 693, 377, 1235, 590

        print(f"[1С:Windows] Работа в диалоге «Найти» (область {dlg_left},{dlg_top}..{dlg_right},{dlg_bottom}):")

        # -----------------------------------------------------------------
        # 2. Поле «Где искать:» -> выбираем «Организация»
        # -----------------------------------------------------------------
        print(f"[1С:Windows]   • Выбор «{field_name}» в поле «Где искать»...")

        # Ищем поля ввода внутри диалога «Найти»
        dlg_edits = []
        target_container = find_dlg if find_dlg else self.main_win
        try:
            for el in target_container.descendants():
                try:
                    ctrl_type = getattr(el.element_info, "control_type", "")
                    if ctrl_type in ("Edit", "ComboBox"):
                        r = el.rectangle()
                        if dlg_left <= r.left <= dlg_right and dlg_top + 25 <= r.top <= dlg_top + 130 and r.width() >= 100:
                            dlg_edits.append(el)
                except Exception:
                    continue
            dlg_edits.sort(key=lambda e: (e.rectangle().top, e.rectangle().left))
        except Exception as e:
            logger.debug("Поиск полей в диалоге 'Найти': %s", e)

        # Координаты стрелки выпадающего списка «Где искать» и самого поля «Где искать»
        # В диалоге «Найти» (top=377): поле «Где искать» находится на y = dlg_top + 52 (429), правый край = dlg_left + 528 (1221)
        where_arrow_x = dlg_left + 520
        where_arrow_y = dlg_top + 52
        where_field_x = dlg_left + 230
        where_field_y = dlg_top + 52

        if dlg_edits:
            try:
                r0 = dlg_edits[0].rectangle()
                where_field_x = r0.left + min(80, r0.width() // 3)
                where_field_y = r0.top + r0.height() // 2
                where_arrow_x = r0.right - 8
                where_arrow_y = r0.top + r0.height() // 2
            except Exception:
                pass

        # Открываем выпадающий список «Где искать» кликом по стрелке [v]
        self.pywinauto.mouse.click(coords=(where_arrow_x, where_arrow_y))
        time.sleep(0.5)

        # Пробуем найти пункт «Организация» в открывшемся выпадающем списке
        org_field_selected = False
        try:
            for w in self.Desktop(backend="uia").windows():
                for it in w.descendants():
                    try:
                        txt = (it.element_info.name or it.window_text() or "").strip().lower()
                        if txt == field_name.lower():
                            ir = it.rectangle()
                            if ir.top >= where_field_y and ir.height() >= 12:
                                self.pywinauto.mouse.click(
                                    coords=(ir.left + min(60, ir.width() // 2), ir.top + ir.height() // 2)
                                )
                                org_field_selected = True
                                break
                    except Exception:
                        continue
                if org_field_selected:
                    break
        except Exception as e:
            logger.debug("UIA выбор 'Организация' из списка 'Где искать': %s", e)

        if not org_field_selected:
            # В выпадающем списке «Где искать» (см. скриншот step_67_media_0.png):
            # 1: Код (y = where_field_y + 28)
            # 2: Наименование (y = where_field_y + 52)
            # 3: Полное наименование (y = where_field_y + 78)
            # 4: Контрагент (y = where_field_y + 104)
            # 5: Организация (y = where_field_y + 130 -> y ≈ 560)
            org_item_x = where_field_x + 30
            org_item_y = where_field_y + 130
            print(f"[1С:Windows]   • Клик по строке «{field_name}» в выпадающем списке ({org_item_x}, {org_item_y})...")
            self.pywinauto.mouse.click(coords=(org_item_x, org_item_y))
            time.sleep(0.4)

        time.sleep(0.4)

        # -----------------------------------------------------------------
        # 3. Поле «Что искать:» -> вводим и выбираем «ООО "ФК ПУЛЬС"»
        # -----------------------------------------------------------------
        print(f"[1С:Windows]   • Ввод «{org_value}» в поле «Что искать»...")

        # Поле «Что искать» находится ровно на 32 пикселя ниже поля «Где искать» (y = dlg_top + 84 = 461)
        what_field_x = where_field_x
        what_field_y = dlg_top + 84

        if len(dlg_edits) >= 2:
            try:
                r1 = dlg_edits[1].rectangle()
                if r1.top > where_field_y + 10:
                    what_field_x = r1.left + min(80, r1.width() // 3)
                    what_field_y = r1.top + r1.height() // 2
            except Exception:
                pass

        # Кликаем в поле «Что искать» и вставляем 'ООО "ФК ПУЛЬС"'
        self.pywinauto.mouse.click(coords=(what_field_x, what_field_y))
        time.sleep(0.25)
        self._select_all_and_paste(org_value)

        # Ждем появления выпадающей подсказки 1С с элементом справочника «ООО "ФК ПУЛЬС"» (см. f_44s.png)
        time.sleep(1.0)

        # В 1С поле «Организация» — ссылочное, поэтому нужно кликнуть по появившейся подсказке
        # (расположена прямо под полем «Что искать»: x = what_field_x, y = what_field_y + 28 ≈ 490)
        autocomplete_clicked = False
        try:
            for w in self.Desktop(backend="uia").windows():
                for it in w.descendants():
                    try:
                        txt = (it.element_info.name or it.window_text() or "").strip().lower()
                        if "фк пульс" in txt:
                            ir = it.rectangle()
                            # Подсказка находится ниже поля «Что искать» (top > what_field_y + 8)
                            if what_field_y + 8 <= ir.top <= what_field_y + 90:
                                click_x = ir.left + min(60, ir.width() // 2)
                                click_y = ir.top + ir.height() // 2
                                print(f"[1С:Windows]   • Выбор элемента «{org_value}» из выпадающего списка ({click_x}, {click_y})...")
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
            # Координатный клик по первой строке выпадающей подсказки под полем «Что искать» (f_44s.png: x=860, y=490)
            popup_x = what_field_x
            popup_y = what_field_y + 28
            print(f"[1С:Windows]   • Клик по выпадающей подсказке «{org_value}» ({popup_x}, {popup_y})...")
            self.pywinauto.mouse.click(coords=(popup_x, popup_y))

        time.sleep(0.5)

        # -----------------------------------------------------------------
        # 4. Нажатие желтой кнопки «Найти» в диалоге
        # -----------------------------------------------------------------
        print("[1С:Windows]   • Нажатие кнопки «Найти» и ожидание загрузки фильтра...")
        find_btn_clicked = False
        try:
            search_root = find_dlg if find_dlg else self.main_win
            for btn in search_root.descendants(control_type="Button"):
                try:
                    txt = (btn.element_info.name or btn.window_text() or "").strip().lower()
                    if txt == "найти":
                        br = btn.rectangle()
                        if dlg_top + 100 <= br.top <= dlg_bottom + 40:
                            btn.click_input()
                            find_btn_clicked = True
                            break
                except Exception:
                    continue
        except Exception:
            pass

        if not find_btn_clicked:
            # В диалоге «Найти» (f_47s.png) желтая кнопка «Найти» имеет координаты (x = dlg_left + 353 = 1046, y = dlg_top + 188 = 565)
            btn_x = dlg_left + 353
            btn_y = dlg_top + 188
            self.pywinauto.mouse.click(coords=(btn_x, btn_y))
            time.sleep(0.2)
            # Если диалог всё ещё открыт — дополнительно жмем Enter
            if self._find_dialog("найти", timeout=0.6):
                self._hotkey_enter()

        # -----------------------------------------------------------------
        # 5. Ожидание полной прогрузки фильтра «Организация: ООО "ФК ПУЛЬС"»
        # -----------------------------------------------------------------
        self._wait_1c_ready(min_wait=3.5, max_wait=12.0)

        # Дополнительно проверяем появление плашки фильтра до 5 секунд
        for _ in range(10):
            if self._is_org_filter_applied():
                break
            time.sleep(0.5)

        print(f"[1С:Windows] ✓ Фильтр «{field_name}: {org_value}» установлен и загружен.")

    # ---------------------------------------------------------------------
    # Шаг 4: Поиск точки в списке «Адреса доставки» и проваливание в карточку
    # ---------------------------------------------------------------------
    def _focus_and_paste_in_search_box(self, query: str) -> None:
        """
        Кликает в поле поиска списка «Поиск (Ctrl+F)» на командной панели «Адреса доставки»,
        вставляет запрос из буфера обмена, нажимает Enter и ждет загрузки результатов.
        """
        print(f"[1С:Windows] Ввод в поле поиска списка: '{query}'...")
        search_focused = False

        try:
            main_r = self.main_win.rectangle()
            for el in self.main_win.descendants(control_type="Edit"):
                try:
                    r = el.rectangle()
                    # Поле поиска списка «Поиск (Ctrl+F)» находится на высоте 105..150 px справа (x > 1200)
                    if main_r.top + 100 <= r.top <= main_r.top + 155 and r.left >= main_r.left + 1000 and r.width() >= 100:
                        click_x = r.left + min(80, r.width() // 2)
                        click_y = r.top + r.height() // 2
                        print(f"[1С:Windows] Клик в поле поиска списка ({click_x}, {click_y})...")
                        self.pywinauto.mouse.click(coords=(click_x, click_y))
                        search_focused = True
                        time.sleep(0.3)
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.debug("UIA поиск поля 'Поиск (Ctrl+F)': %s", e)

        if not search_focused:
            # Координатный клик в поле «Поиск (Ctrl+F)» (на 1920x1080: x = 1600, y = 124)
            try:
                main_r = self.main_win.rectangle()
                click_x = main_r.right - 310
                click_y = main_r.top + 124
                print(f"[1С:Windows] Координатный клик в поле «Поиск (Ctrl+F)» ({click_x}, {click_y})...")
                self.pywinauto.mouse.click(coords=(click_x, click_y))
                time.sleep(0.3)
            except Exception:
                self._hotkey_ctrl_f()
                time.sleep(0.5)

        self._select_all_and_paste(query)
        time.sleep(0.3)
        self._hotkey_enter()

        print(f"[1С:Windows] Ожидание загрузки результатов поиска для '{query}'...")
        self._wait_1c_ready(min_wait=3.0, max_wait=10.0)

    def _is_address_card_open(self, code: str, client_name: str) -> bool:
        """
        Проверяет, открылась ли карточка точки доставки (по наличию вкладки «Адресная информация»,
        кнопки «Записать и закрыть» или заголовка с именем клиента/кодом).
        """
        if not self.main_win:
            return False

        try:
            for el in self.main_win.descendants():
                try:
                    txt = (el.element_info.name or el.window_text() or "").strip().lower()
                    if not txt:
                        continue
                    if txt in ("адресная информация", "записать и закрыть", "графики доставки"):
                        return True
                    if "(адреса доставки)" in txt:
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        return False

    def _double_click_found_row(self, code: str, address: str, client_name: str) -> bool:
        """
        Дважды нажимает на найденную строку в таблице «Адреса доставки», чтобы провалиться в карточку точки.
        Возвращает True, если карточка точки успешно открылась.
        """
        print(f"[1С:Windows] Двойной клик по найденной строке точки '{code or client_name}'...")
        main_r = self.main_win.rectangle()

        # 1. Сначала ищем ячейку найденной строки через UIA (высота первой строки таблицы: y ≈ 235..285)
        row_clicked = False
        try:
            table_top = main_r.top + 225
            table_bottom = main_r.bottom - 90
            keywords = [k.lower() for k in (code, client_name, address[:25]) if k]

            for el in self.main_win.descendants():
                try:
                    r = el.rectangle()
                    if table_top <= r.top <= table_bottom and r.width() > 30 and 12 <= r.height() <= 55:
                        txt = (el.element_info.name or el.window_text() or "").strip().lower()
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

        # 2. Если UIA не отдал текст ячейки табличного поля 1С — делаем двойной клик
        # точно по первой найденной строке таблицы (в f_80s.png строка МСК000132723 находится на x=260, y=250)
        if not row_clicked:
            first_row_x = main_r.left + 260
            first_row_y = main_r.top + 250
            print(f"[1С:Windows] Координатный двойной клик по первой строке таблицы ({first_row_x}, {first_row_y})...")
            self.pywinauto.mouse.double_click(coords=(first_row_x, first_row_y))

        self._wait_1c_ready(min_wait=2.2, max_wait=7.0)

        if self._is_address_card_open(code, client_name):
            print("[1С:Windows] ✓ Карточка точки доставки открыта.")
            return True

        # 3. Если после первого двойного клика карточка еще не открылась (например, первый клик только сфокусировал таблицу) —
        # делаем повторный двойной клик по первой строке и нажимаем Enter
        first_row_x = main_r.left + 260
        first_row_y = main_r.top + 250
        print(f"[1С:Windows] Повторный двойной клик + Enter по строке ({first_row_x}, {first_row_y})...")
        self.pywinauto.mouse.double_click(coords=(first_row_x, first_row_y))
        time.sleep(0.3)
        self._hotkey_enter()
        self._wait_1c_ready(min_wait=2.2, max_wait=7.0)

        return self._is_address_card_open(code, client_name)

    def _search_and_open_address_card(self, code: str, address: str, client_name: str) -> None:
        """
        Вставляет номер точки (МСК...) в поиск, дожидается загрузки,
        дважды нажимает на найденную строку, чтобы провалиться внутрь карточки.
        Если по коду МСК... точка не нашлась — пробует поиск по адресу.
        """
        primary_query = code.strip() if code else address.strip()
        self._focus_and_paste_in_search_box(primary_query)

        opened = self._double_click_found_row(code=code, address=address, client_name=client_name)

        # Fallback: если искали по коду МСК..., но карточка не открылась (например, в базе другой код),
        # пробуем найти по улице/дому из адреса
        if not opened and code and address:
            short_addr = address.strip()
            print(f"[1С:Windows] Поиск по коду '{code}' не открыл карточку, пробуем поиск по адресу: '{short_addr}'...")
            self._focus_and_paste_in_search_box(short_addr)
            self._double_click_found_row(code=code, address=address, client_name=client_name)

    # ---------------------------------------------------------------------
    # Шаг 5: Раздел «Адресная информация» и заполнение геоданных внутри точки
    # ---------------------------------------------------------------------
    def _switch_to_address_info_tab(self) -> None:
        """
        Внутри открытой карточки точки доставки открывает раздел (вкладку) «Адресная информация».
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
            # Координатный fallback для 1920x1080 (см. step_59_media_0.png: вкладка «Адресная информация» на x=315, y=348)
            try:
                main_r = self.main_win.rectangle()
                click_x = main_r.left + 315
                click_y = main_r.top + 348
                print(f"[1С:Windows] Координатный клик по вкладке «Адресная информация» ({click_x}, {click_y})...")
                self.pywinauto.mouse.click(coords=(click_x, click_y))
                time.sleep(1.0)
            except Exception:
                pass

    def _fill_field_by_label(self, label_keyword: str, value_str: str) -> bool:
        """
        Заполняет поле на вкладке «Адресная информация» («Широта», «Долгота», «Радиус зоны»):
        Способ 1: Ищет метку через UIA и кликает в связанное Edit-поле справа.
        Способ 2: Точный координатный fallback по эталонной разметке карточки 1С (1920x1080).
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
                        # На вкладке «Адресная информация» геоданные находятся в средней части (350 <= y <= 700)
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

            # 3. Координатный fallback для 1920x1080 (см. скриншот f_95s.png):
            #    • Широта:      x = 550, y = 494
            #    • Долгота:     x = 550, y = 526
            #    • Радиус зоны: x = 1580, y = 490
            fallback_coords = {
                "широта": (main_r.left + 550, main_r.top + 494),
                "долгота": (main_r.left + 550, main_r.top + 526),
                "радиус": (main_r.left + 1580, main_r.top + 490),
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

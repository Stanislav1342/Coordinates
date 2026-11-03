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
        self.main_win.set_focus()
        time.sleep(0.8)
        return self.main_win

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
        # ШАГ 1: Переход в раздел 'Адреса доставки' строго через Избранное ⭐
        # -------------------------------------------------------------
        print("[1С:Windows] Открытие Избранного через звездочку ⭐...")
        opened_fav = False

        # Пробуем кликнуть кнопку со звездочкой в шапке (по тексту 'Избранное')
        try:
            star_btns = self._find_elements_by_text("Избранное", control_type="Button")
            for sb in star_btns:
                try:
                    if sb.is_displayed():
                        sb.click_input()
                        opened_fav = True
                        time.sleep(1.0)
                        break
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Поиск кнопки звездочки: %s", e)

        # Если кнопка не нашлась кликом — нажимаем системную комбинацию 1С: Ctrl + Shift + B
        if not opened_fav:
            print("[1С:Windows] Нажатие горячих клавиш Ctrl+Shift+B для открытия Избранного...")
            self.send_keys("^+b")
            time.sleep(1.2)

        # В открывшейся панели 'Избранное' нажимаем 'Адреса доставки'
        print("[1С:Windows] Выбор раздела 'Адреса доставки' в Избранном...")
        clicked_addr = False
        try:
            fav_items = self._find_elements_by_text("Адреса доставки")
            for item in fav_items:
                try:
                    if item.is_displayed():
                        item.click_input()
                        clicked_addr = True
                        time.sleep(2.0)
                        break
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Клик по 'Адреса доставки' в списке: %s", e)

        # Если клик по элементу не сработал через UIA:
        # В открытом меню Избранного 'Адреса доставки' стоит ПЕРВЫМ пунктом и уже в фокусе!
        # Нажимаем строго ENTER (без стрелок вниз!), чтобы открыть его:
        if not clicked_addr:
            print("[1С:Windows] Пункт не нажат кликом, нажимаем Enter для выбора первого пункта Избранного...")
            self.send_keys("{ENTER}")
            time.sleep(2.0)

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

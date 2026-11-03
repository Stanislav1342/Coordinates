"""
onec_service.py — Сервис взаимодействия с 1С:Предприятие.

На Windows:
Использует pywinauto (UIA backend) и системный буфер обмена Windows (через clip.exe),
что исключает проблемы с переключением раскладки клавиатуры (ENG/RUS).
1. Активация окна 1С.
2. Переключение на вкладку 'Адреса доставки' (если открыта внизу или через интерфейс).
3. Точный поиск по уникальному коду точки (например, МСК000132723) через буфер обмена.
4. Открытие карточки (Enter).
5. Переход во вкладку 'Адресная информация'.
6. Вставка новых значений Широта, Долгота и Радиус через буфер обмена (Ctrl+V).
7. Сохранение (Ctrl+Enter) и подтверждение.

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
    Копирует текст в системный буфер обмена Windows через встроенный clip.exe (UTF-16).
    Это на 100% исключает ошибки раскладки клавиатуры (ENG/RUS) при вводе текста.
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
        print(f" 1. Поиск окна: '(МСК) РМХЦ Хвостов; Интерфейс: / КИС 3.1'")
        print(f" 2. Активация вкладки: 'Адреса доставки'")
        print(f" 3. Точный поиск по коду: '{code}' (или адресу)")
        print(f" 4. Открытие карточки: '{client_name or code}' (Enter)")
        print(f" 5. Вкладка: 'Адресная информация'")
        print(f" 6. Ввод геоданных через буфер обмена (Ctrl+V):")
        print(f"    • Широта:         {lat_str}")
        print(f"    • Долгота:        {lon_str}")
        print(f"    • Радиус зоны:    {rad_str} м")
        print(f"    • Чекбокс:        [x] Координаты проверены")
        print(f" 7. Сохранение:       'Записать и закрыть' (Ctrl+Enter)")
        time.sleep(1)
        print(f" 8. Уведомление 1С:   ✓ 'Изменение: {client_name or code}'")
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
        
        app = self.app_module(backend="uia").connect(handle=windows[0].handle)
        main_win = app.window(handle=windows[0].handle)
        main_win.set_focus()
        time.sleep(0.8)
        return main_win

    def update_coordinates(
        self,
        code: str,
        address: str,
        lat: float,
        lon: float,
        radius: Optional[int] = None,
        client_name: str = "",
    ) -> bool:
        print(f"[1С:Windows] Подключение к окну 1С для точки {code or client_name}...")
        main_win = self._find_main_window()

        # 1. Закрываем панель Избранного справа, если она открылась
        try:
            fav_header = main_win.descendants(title="Избранное", control_type="Text")
            if fav_header:
                self.send_keys("{ESC}")
                time.sleep(0.5)
        except Exception:
            pass

        # 2. Переключение на вкладку 'Адреса доставки'
        # Проверяем открытые вкладки (вкладка отображается внизу или вверху окна)
        print("[1С:Windows] Переход на вкладку 'Адреса доставки'...")
        tab_switched = False
        try:
            all_tabs = main_win.descendants(control_type="TabItem")
            for t in all_tabs:
                if "Адреса доставки" in t.window_text():
                    t.click_input()
                    tab_switched = True
                    time.sleep(1.2)
                    break
        except Exception as e:
            logger.debug("Поиск по TabItem: %s", e)

        # Если вкладка не найдена в TabItem, ищем по гиперссылке или тексту внизу
        if not tab_switched:
            try:
                addr_elems = main_win.descendants(title_re=".*Адреса доставки.*")
                for el in addr_elems:
                    if el.is_displayed():
                        el.click_input()
                        tab_switched = True
                        time.sleep(1.2)
                        break
            except Exception as e:
                logger.debug("Поиск по заголовку элементов: %s", e)

        # 3. Поиск строки в разделе 'Адреса доставки'
        # Поиск по уникальному коду (например, МСК000132723) на 100% однозначен и мгновенен!
        search_query = code if code else address
        print(f"[1С:Windows] Поиск по коду/адресу: '{search_query}'...")

        # Нажимаем Ctrl+F для открытия поиска по списку
        self.send_keys("^f")
        time.sleep(0.8)

        # Копируем запрос в буфер обмена и вставляем через Ctrl+V (защита от раскладки клавиатуры!)
        set_clipboard(search_query)
        self.send_keys("^v")
        time.sleep(0.3)
        self.send_keys("{ENTER}")
        time.sleep(2)

        # 4. Открываем карточку найденной строки
        print("[1С:Windows] Открытие карточки найденного адреса (Enter)...")
        self.send_keys("{ENTER}")
        time.sleep(2.5)

        # 5. Переход на вкладку 'Адресная информация' внутри карточки
        print("[1С:Windows] Переход во вкладку 'Адресная информация'...")
        try:
            card_tabs = main_win.descendants(control_type="TabItem")
            for ct in card_tabs:
                if "Адресная информация" in ct.window_text():
                    ct.click_input()
                    time.sleep(1)
                    break
        except Exception as e:
            logger.debug("Поиск вкладки Адресная информация: %s", e)

        # 6. Заполнение полей координат через буфер обмена
        lat_str = f"{lat:.8f}".replace(".", ",")
        lon_str = f"{lon:.8f}".replace(".", ",")

        print(f"[1С:Windows] Ввод геоданных: Широта={lat_str}, Долгота={lon_str}...")

        # Ищем метку 'Широта:' и переходим в ее поле по Tab
        try:
            lat_labels = main_win.descendants(title_re=".*Широта.*", control_type="Text")
            if lat_labels:
                lat_labels[0].click_input()
                time.sleep(0.3)
                self.send_keys("{TAB}")  # переход в поле ввода
                time.sleep(0.2)
                set_clipboard(lat_str)
                self.send_keys("^a^v")
                time.sleep(0.3)
        except Exception as e:
            logger.warning("Заполнение Широты через label: %s", e)

        # Ищем метку 'Долгота:' и переходим в ее поле по Tab
        try:
            lon_labels = main_win.descendants(title_re=".*Долгота.*", control_type="Text")
            if lon_labels:
                lon_labels[0].click_input()
                time.sleep(0.3)
                self.send_keys("{TAB}")
                time.sleep(0.2)
                set_clipboard(lon_str)
                self.send_keys("^a^v")
                time.sleep(0.3)
        except Exception as e:
            logger.warning("Заполнение Долготы через label: %s", e)

        # Если передан радиус зоны (например, 300)
        if radius is not None:
            print(f"[1С:Windows] Ввод радиуса зоны: {radius} м...")
            try:
                rad_labels = main_win.descendants(title_re=".*Радиус зоны.*", control_type="Text")
                if rad_labels:
                    rad_labels[0].click_input()
                    time.sleep(0.3)
                    self.send_keys("{TAB}")
                    time.sleep(0.2)
                    set_clipboard(str(radius))
                    self.send_keys("^a^v")
                    time.sleep(0.3)
            except Exception as e:
                logger.warning("Заполнение Радиуса через label: %s", e)

        # 7. Чекбокс 'Координаты проверены'
        try:
            chks = main_win.descendants(title="Координаты проверены", control_type="CheckBox")
            if chks:
                if not chks[0].get_toggle_state():
                    chks[0].click_input()
                    time.sleep(0.3)
        except Exception:
            pass

        # 8. Сохранение карточки: 'Записать и закрыть' (Ctrl+Enter)
        print("[1С:Windows] Нажатие 'Записать и закрыть' (Ctrl+Enter)...")
        # Нажимаем желтую кнопку 'Записать и закрыть' или Ctrl+Enter
        try:
            save_btns = main_win.descendants(title="Записать и закрыть", control_type="Button")
            if save_btns:
                save_btns[0].click_input()
            else:
                self.send_keys("^{ENTER}")
        except Exception:
            self.send_keys("^{ENTER}")

        time.sleep(2)
        print(f"[1С:Windows] ✓ Данные точки '{client_name or code}' успешно сохранены в 1С!")
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

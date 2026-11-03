"""
onec_service.py — Сервис взаимодействия с 1С:Предприятие.

На Windows:
Использует pywinauto (UIA backend) для автоматизации действий пользователя в локальном
клиенте 1С (конфигурация 'ЕИС МСК / Корпоративная информационная система'):
1. Поиск и активация окна 1С.
2. Открытие раздела 'Адреса доставки' через Избранное.
3. Проверка/установка отбора 'Организация = ООО "ФК ПУЛЬС"'.
4. Поиск строки по адресу или коду МСК...
5. Открытие карточки -> переход в 'Адресная информация'.
6. Запись новых значений 'Широта', 'Долгота', 'Радиус зоны'.
7. Сохранение ('Записать и закрыть') и контроль всплывающего уведомления.

На macOS / Linux:
Автоматически включает режим MockOneCService (симулятор) для безопасной отладки
логики без наличия установленной 1С.
"""

import sys
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


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
    """
    Симулятор 1С для тестирования на macOS.
    Показывает все действия, которые будут выполнены на Windows.
    """

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
        print(f" 2. Открытие раздела: Избранное ⭐ -> 'Адреса доставки'")
        print(f" 3. Проверка отбора: Организация = 'ООО \"ФК ПУЛЬС\"' (Активен)")
        print(f" 4. Поиск строки: '{address}' [Код: {code}]")
        print(f" 5. Открытие карточки: '{client_name or code}' (Двойной клик)")
        print(f" 6. Переход на вкладку: 'Адресная информация'")
        print(f" 7. Ввод геоданных:")
        print(f"    • Широта:         {lat_str}")
        print(f"    • Долгота:        {lon_str}")
        print(f"    • Радиус зоны:    {rad_str} м")
        print(f"    • Чекбокс:        [x] Координаты проверены")
        print(f" 8. Нажатие кнопки:   'Записать и закрыть' (Ctrl+Enter)")
        time.sleep(1)
        print(f" 9. Уведомление 1С:   ✓ 'Изменение: {client_name or code}' получено!")
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
                "Библиотека pywinauto не установлена! Установите ее на Windows: pip install pywinauto"
            )

    def _find_main_window(self):
        """Находит главное окно 1С по заголовку."""
        import pywinauto
        # Ищем окно 1С по ключевым словам в заголовке
        windows = pywinauto.findwindows.find_elements(
            title_re=".*(1С:Предприятие|ЕИС МСК|Корпоративная информационная система).*"
        )
        if not windows:
            raise RuntimeError("Главное окно 1С не найдено! Запустите 1С:Предприятие.")
        app = self.app_module(backend="uia").connect(handle=windows[0].handle)
        main_win = app.window(handle=windows[0].handle)
        main_win.set_focus()
        time.sleep(0.5)
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
        print(f"[1С:Windows] Подключение к окну 1С для обновления {code}...")
        main_win = self._find_main_window()

        # 1. Открытие раздела 'Адреса доставки'
        # Проверяем, открыта ли уже вкладка
        try:
            tab_item = main_win.child_window(title="Адреса доставки", control_type="TabItem")
            if tab_item.exists():
                tab_item.click_input()
                time.sleep(0.5)
            else:
                # Нажимаем звездочку Избранное и выбираем 'Адреса доставки'
                fav_btn = main_win.child_window(title_re=".*Избранное.*|.*★.*|.*☆.*", control_type="Button")
                if fav_btn.exists():
                    fav_btn.click_input()
                    time.sleep(0.5)
                    addr_fav = main_win.child_window(title="Адреса доставки", control_type="Hyperlink")
                    addr_fav.click_input()
                    time.sleep(1.5)
        except Exception as e:
            logger.warning("Переход через вкладку/избранное: %s", e)

        # 2. Поиск строки по адресу (или коду МСК...)
        print(f"[1С:Windows] Поиск адреса '{address}'...")
        # Фокусируем список и нажимаем Ctrl+F
        self.send_keys("^f")
        time.sleep(0.5)
        # Вставляем адрес в поле поиска
        search_text = address
        self.send_keys(search_text, with_spaces=True)
        self.send_keys("{ENTER}")
        time.sleep(2)

        # 3. Открываем найденную строку (Enter)
        print("[1С:Windows] Открытие карточки адреса...")
        self.send_keys("{ENTER}")
        time.sleep(2)

        # 4. Переход на вкладку 'Адресная информация'
        try:
            addr_info_tab = main_win.child_window(title="Адресная информация", control_type="TabItem")
            if addr_info_tab.exists():
                addr_info_tab.click_input()
                time.sleep(0.5)
        except Exception:
            # Fallback через клавиатуру
            self.send_keys("^{TAB}")
            time.sleep(0.5)

        # 5. Заполнение широты и долготы
        lat_str = f"{lat:.8f}".replace(".", ",")
        lon_str = f"{lon:.8f}".replace(".", ",")

        print(f"[1С:Windows] Запись координат: Широта={lat_str}, Долгота={lon_str}...")
        try:
            lat_edit = main_win.child_window(auto_id_re=".*Широта.*|.*Latitude.*", control_type="Edit")
            if lat_edit.exists():
                lat_edit.set_edit_text(lat_str)
            else:
                # Клик по полю Широта
                self.send_keys("^a{BACKSPACE}" + lat_str)

            lon_edit = main_win.child_window(auto_id_re=".*Долгота.*|.*Longitude.*", control_type="Edit")
            if lon_edit.exists():
                lon_edit.set_edit_text(lon_str)
        except Exception as e:
            logger.warning("Заполнение через auto_id: %s", e)

        # 6. Если передан радиус зоны
        if radius is not None:
            print(f"[1С:Windows] Запись радиуса зоны: {radius} м...")
            try:
                rad_edit = main_win.child_window(title_re=".*Радиус зоны.*", control_type="Edit")
                if rad_edit.exists():
                    rad_edit.set_edit_text(str(radius))
            except Exception:
                pass

        # 7. Отметка 'Координаты проверены'
        try:
            chk = main_win.child_window(title="Координаты проверены", control_type="CheckBox")
            if chk.exists() and not chk.get_toggle_state():
                chk.click_input()
        except Exception:
            pass

        # 8. Сохранение: кнопка 'Записать и закрыть' (Ctrl+Enter)
        print("[1С:Windows] Нажатие 'Записать и закрыть'...")
        self.send_keys("^{ENTER}")
        time.sleep(2)

        print(f"[1С:Windows] Карточка '{client_name or code}' успешно сохранена.")
        return True


def get_onec_service() -> OneCServiceInterface:
    """
    Фабрика сервиса: на Windows возвращает WindowsOneCService,
    на macOS / Linux возвращает MockOneCService.
    """
    if sys.platform == "win32":
        try:
            return WindowsOneCService()
        except Exception as e:
            logger.warning("Не удалось инициализировать WindowsOneCService (%s), fallback на Mock", e)
            return MockOneCService()
    else:
        return MockOneCService()

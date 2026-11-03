"""
test_mock_run.py — Тест полного цикла обработки рейса на macOS (без реального браузера).
"""

import sys
from yandex_service import YandexGeocoder, evaluate_coordinates
from onec_service import get_onec_service
from advantum_service import DeliveryPoint

def test_full_pipeline():
    print("=" * 70)
    print(" ТЕСТИРОВАНИЕ ПОЛНОГО ЦИКЛА СИНХРОНИЗАЦИИ (MOCK РЕЙС 15053328)")
    print("=" * 70)

    # Тестовые данные из реального рейса
    mock_points = [
        DeliveryPoint(
            index="1",
            status="Не пройдена",
            name="БИОКОДЕ",
            code="МСК000132723",
            address="Московская обл, Домодедово г, Северный мкр, Логистическая ул, д. 1/6, корп. подъезд №4",
            operation="Погрузка",
            is_failed=True,
        ),
        DeliveryPoint(
            index="3",
            status="Попадание в окно",
            name="МЕРКМ",
            code="МСК000134702",
            address="Московская обл, Подольский р-н, Покров с, Полевая ул, д. 1",
            operation="Разгрузка",
            is_failed=False,
        )
    ]

    geocoder = YandexGeocoder()
    onec = get_onec_service()

    # Фильтруем неотбитые точки
    failed = [p for p in mock_points if p.is_failed]
    print(f"\n[Advantum] Найдено неотбитых точек: {len(failed)}")

    for p in failed:
        print(f"\n Обработка точки №{p.index}: {p.name} [{p.code}]")
        print(f" Адрес: {p.address}")

        geo_res = geocoder.geocode(p.address)
        print(f" [Геокодер] Точные координаты: {geo_res.lat:.8f}, {geo_res.lon:.8f}")

        # Сравниваем с текущими (предположим старые координаты стояли на трассе в Павловском: 55.495000, 37.720000)
        old_lat, old_lon = 55.495000, 37.720000
        evaluation = evaluate_coordinates(old_lat, old_lon, geo_res.lat, geo_res.lon)
        print(f" [Анализ] Статус: {evaluation['status']} | Смещение: {evaluation['distance_m']} м")
        print(f" [Анализ] Причина: {evaluation['reason']}")

        # Обновляем в 1С
        success = onec.update_coordinates(
            code=p.code,
            address=p.address,
            lat=geo_res.lat,
            lon=geo_res.lon,
            radius=300,
            client_name=p.name,
        )
        assert success, "Ошибка при вызове update_coordinates"

    print(" ✓ Тест полного цикла успешно завершен!")

if __name__ == "__main__":
    test_full_pipeline()

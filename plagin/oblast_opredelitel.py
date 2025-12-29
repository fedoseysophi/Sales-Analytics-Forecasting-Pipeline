import reverse_geocoder as rg
from sqlalchemy import create_engine, text

# --- НАСТРОЙКИ ---
DB_URI = "postgresql://postgres:pip1234@localhost:5432/postgres"


def fill_geo_oblast():
    engine = create_engine(DB_URI)

    # 1. Создаем колонку, если нет
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE wb_pickup_points ADD COLUMN IF NOT EXISTS geo_oblast TEXT;"))

    # 2. Загружаем координаты
    print("Загружаем точки...")
    points = []
    with engine.connect() as conn:
        # Берем точки с координатами
        result = conn.execute(text("SELECT id, lat, lon FROM wb_pickup_points WHERE lat IS NOT NULL"))
        points = result.fetchall()

    if not points:
        print("Нет данных.")
        return

    print(f"Обрабатываем {len(points)} записей...")

    # 3. Определяем регион
    coords = [(p.lat, p.lon) for p in points]
    geo_results = rg.search(coords)  # Магия reverse_geocoder

    # 4. Готовим данные для обновления
    updates = []
    for i, res in enumerate(geo_results):
        # res['admin1'] - это область/регион (напр. 'Moskovskaya Oblast')
        # res['cc'] - код страны (RU)

        region_name = res.get('admin1', '')
        country = res.get('cc', '')

        # Небольшая очистка: если страна KZ/BY, можно дописать это в регион для ясности,
        # но пока пишем просто регион как есть.

        updates.append({
            "p_id": points[i].id,
            "oblast": region_name
        })

    # 5. Записываем в базу (batch update)
    print("Сохраняем в geo_oblast...")
    with engine.begin() as conn:
        stmt = text("UPDATE wb_pickup_points SET geo_oblast = :oblast WHERE id = :p_id")
        conn.execute(stmt, updates)

    print("Успешно! Проверьте колонку geo_oblast в базе.")


if __name__ == "__main__":
    fill_geo_oblast()

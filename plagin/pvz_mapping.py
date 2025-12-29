import json
from sqlalchemy import create_engine, text

# --- НАСТРОЙКИ ---
# Путь к скачанному файлу JSON на вашем диске
FILE_PATH = "all-poo-fr-v8.json"

# Ваша строка подключения (локальная БД)
DB_URI = "postgresql://postgres:pip1234@localhost:5432/postgres"


def load_data():
    # 1. Создаем подключение (Engine)
    engine = create_engine(DB_URI)

    # 2. Создаем таблицу (если её нет)
    # Мы используем raw SQL для простоты, чтобы не описывать модели ORM
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS wb_pickup_points (
        id SERIAL PRIMARY KEY,
        wb_id BIGINT UNIQUE,            -- ID ПВЗ (из JSON)
        country_code TEXT,              -- Код страны (ru, kz, by...)
        city TEXT,                      -- Город (распарсенный)
        address TEXT,                   -- Полный адрес
        lat FLOAT,                      -- Широта
        lon FLOAT,                      -- Долгота
        raw_data JSONB,                 -- Сохраним весь объект на всякий случай
        updated_at TIMESTAMP DEFAULT NOW()
    );
    """

    with engine.connect() as conn:
        conn.execute(text(create_table_sql))
        conn.commit()
        print("Таблица проверена/создана.")

    # 3. Читаем и парсим JSON
    print(f"Чтение файла {FILE_PATH}...")
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    # Учитываем структуру: это может быть словарь {"value": [...]} или сразу список [...]
    # На вашем скриншоте видно, что внутри лежат объекты с ключом "country"
    data_list = raw_data.get('value', raw_data) if isinstance(raw_data, dict) else raw_data

    prepared_rows = []

    print("Обработка данных...")
    # Проходим по списку стран (верхний уровень вложенности)
    for country_block in data_list:
        # country_block выглядит как: {"country": "ru", "items": [...]}
        c_code = country_block.get("country", "unknown")
        items = country_block.get("items", [])

        print(f"Страна: {c_code}, найдено точек: {len(items)}")

        for item in items:
            # Извлекаем данные точки
            p_id = item.get("id")
            address = item.get("address", "")
            coords = item.get("coordinates", [None, None])  # [lat, lon]

            # Простая логика извлечения города (все что до первой запятой)
            # Например: "г. Москва, ул..." -> "г. Москва" -> "Москва"
            city_extract = address.split(",")[0].replace("г. ", "").strip()

            if p_id:
                prepared_rows.append({
                    "wb_id": p_id,
                    "country_code": c_code,
                    "city": city_extract,
                    "address": address,
                    "lat": coords[0] if coords else None,
                    "lon": coords[1] if coords else None,
                    "raw_data": json.dumps(item, ensure_ascii=False)  # Сохраняем оригинал для истории
                })

    print(f"Всего подготовлено к загрузке: {len(prepared_rows)} записей.")

    # 4. Загружаем в БД с учетом Upsert (обновление дублей)
    # Используем синтаксис PostgreSQL: ON CONFLICT (wb_id) DO UPDATE ...
    insert_sql = text("""
        INSERT INTO wb_pickup_points (wb_id, country_code, city, address, lat, lon, raw_data)
        VALUES (:wb_id, :country_code, :city, :address, :lat, :lon, :raw_data)
        ON CONFLICT (wb_id) DO UPDATE 
        SET 
            country_code = EXCLUDED.country_code,
            city = EXCLUDED.city,
            address = EXCLUDED.address,
            lat = EXCLUDED.lat,
            lon = EXCLUDED.lon,
            updated_at = NOW();
    """)

    # Вставляем пачками (batch), чтобы не забить память
    batch_size = 5000
    with engine.begin() as conn:  # .begin() автоматически делает commit в конце
        for i in range(0, len(prepared_rows), batch_size):
            batch = prepared_rows[i: i + batch_size]
            conn.execute(insert_sql, batch)
            print(f"Загружено {i + len(batch)} из {len(prepared_rows)}...")

    print("Успешно завершено!")


if __name__ == "__main__":
    load_data()

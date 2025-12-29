from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
import requests
import json
from sqlalchemy import create_engine, text

# --- НАСТРОЙКИ БАЗЫ ---
DB_URI = "postgresql://postgres:pip1234@localhost:5432/postgres"
engine = create_engine(DB_URI)

app = FastAPI(title="WB Forecasting API")


# 1. МОДЕЛЬ ДАННЫХ (Что мы ждем от Google Таблицы)
class ForecastRequest(BaseModel):
    wb_api_key: str
    date_from: str  # "2024-09-01"
    date_to: str  # "2024-12-30"


# 2. ФУНКЦИЯ ПРОГНОЗА (Пока заглушка, сюда потом подключим XGBoost)
def make_simple_forecast(df: pd.DataFrame) -> int:
    # Логика: берем среднее кол-во продаж и умножаем на 30 дней
    if df.empty:
        return 0
    avg_daily_sales = df['quantity'].sum() / len(df)
    forecast_next_month = int(avg_daily_sales * 1.1)  # +10% рост
    return forecast_next_month


# 3. ГЛАВНЫЙ ENDPOINT (Маршрут)
@app.post("/load_and_predict")
async def process_data(item: ForecastRequest):
    print(f"📨 Получен запрос! Даты: {item.date_from} - {item.date_to}")

    # --- ЭТАП 1: СКАЧИВАЕМ ДАННЫЕ С WB ---
    url = "https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod"
    headers = {"Authorization": item.wb_api_key}  # <-- Ключ берем из запроса!
    params = {
        "dateFrom": item.date_from,
        "dateTo": item.date_to
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Неверный API ключ Wildberries")
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка WB: {str(e)}")

    if not data:
        return {"status": "ok", "message": "Продаж нет", "forecast": 0}

    # --- ЭТАП 2: ОБРАБОТКА PANDAS ---
    df = pd.DataFrame(data)

    # Очистка от NaN (важно!)
    df = df.where(pd.notnull(df), None)

    df_save = pd.DataFrame()

    # КЛЮЧЕВОЙ МОМЕНТ: Сохраняем токен того, кто сделал запрос


    df_save['rrd_id'] = df['rrd_id']
    df_save['nm_id'] = df['nm_id']
    df_save['wb_api_token'] = item.wb_api_key
    df_save['date_from'] = pd.to_datetime(df['date_from'])
    df_save['date_to'] = pd.to_datetime(df['date_to'])
    df_save['sale_dt'] = pd.to_datetime(df['sale_dt'])

    # Аналитика
    df_save['doc_type_name'] = df['doc_type_name']
    df_save['office_name'] = df['office_name']
    df_save['supplier_oper_name'] = df['supplier_oper_name']

    # Финансы
    df_save['subject_name'] = df['subject_name']
    df_save['brand_name'] = df['brand_name']
    df_save['quantity'] = df['quantity']
    df_save['retail_price'] = df['retail_price']
    df_save['retail_amount'] = df['retail_amount']
    df_save['pricelogistic'] = df['delivery_rub']
    df_save['commission_percent'] = df['commission_percent']

    # JSON
    df_save['raw_data'] = df.apply(lambda x: json.dumps(x.to_dict(), ensure_ascii=False, default=str), axis=1)

    # --- ЭТАП 3: СОХРАНЕНИЕ В БАЗУ ---
    try:
        rows_saved = df_save.to_sql('operations_2', engine, if_exists='append', index=False, method='multi',
                                    chunksize=1000)
        print(f"💾 Сохранено строк: {len(df_save)}")
    except Exception as e:
        print(f"⚠️ Данные уже есть в базе (дубликаты): {e}")
        # Мы не останавливаемся, идем считать прогноз

    # --- ЭТАП 4: ПРОГНОЗ ---
    forecast_val = make_simple_forecast(df_save)

    return {
        "status": "success",
        "loaded_rows": len(df_save),
        "forecast_result": forecast_val,
        "message": f"Успешно загружено {len(df_save)} продаж. Прогноз: {forecast_val} шт."
    }

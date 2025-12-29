from fastapi import FastAPI, HTTPException, Header, Query
import pandas as pd
import requests
import json
from sqlalchemy import create_engine
from typing import Optional

# --- НАСТРОЙКИ БАЗЫ ---
DB_URI = "postgresql://postgres:pip1234@localhost:5432/postgres"
engine = create_engine(DB_URI)

app = FastAPI(title="WB Forecasting API")


# Функция простого прогноза (заглушка)
def make_simple_forecast(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    avg_daily_sales = df['quantity'].sum() / len(df)
    return int(avg_daily_sales * 1.1)  # +10%


@app.post("/load_and_predict")
async def process_data(
        # 1. Токен теперь ждем в заголовке 'Authorization'
        authorization: str = Header(..., description="Ваш WB API Token"),

        # 2. Даты теперь ждем как параметры запроса ?date_from=...&date_to=...
        date_from: str = Query(..., example="2024-11-01"),
        date_to: str = Query(..., example="2024-11-20")
):
    print(f"📨 Запрос: {date_from} - {date_to}")

    # --- ЭТАП 1: СКАЧИВАЕМ ДАННЫЕ С WB ---
    url = "https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod"

    # Пробрасываем токен, который прислал пользователь
    headers_wb = {"Authorization": authorization}
    params_wb = {
        "dateFrom": date_from,
        "dateTo": date_to
    }

    try:
        response = requests.get(url, headers=headers_wb, params=params_wb)
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Неверный токен WB (Wildberries отклонил доступ)")
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка соединения с WB: {str(e)}")

    if not data:
        return {"status": "ok", "message": "Продаж за этот период нет", "forecast": 0}

    # --- ЭТАП 2: ОБРАБОТКА PANDAS ---
    df = pd.DataFrame(data)
    df = df.where(pd.notnull(df), None)  # Чистим NaN

    df_save = pd.DataFrame()

    # Сохраняем тот токен, под которым пришли данные
    df_save['wb_api_token'] = authorization

    # Заполняем поля (как и раньше)
    df_save['rrd_id'] = df['rrd_id']
    df_save['nm_id'] = df['nm_id']
    df_save['date_from'] = pd.to_datetime(df['date_from'])
    df_save['date_to'] = pd.to_datetime(df['date_to'])
    df_save['sale_dt'] = pd.to_datetime(df['sale_dt'])

    df_save['doc_type_name'] = df['doc_type_name']
    df_save['office_name'] = df['office_name']
    df_save['supplier_oper_name'] = df['supplier_oper_name']

    df_save['subject_name'] = df['subject_name']
    df_save['brand_name'] = df['brand_name']
    df_save['quantity'] = df['quantity']
    df_save['retail_price'] = df['retail_price']
    df_save['retail_amount'] = df['retail_amount']
    df_save['pricelogistic'] = df['delivery_rub']
    df_save['commission_percent'] = df['commission_percent']

    df_save['raw_data'] = df.apply(lambda x: json.dumps(x.to_dict(), ensure_ascii=False, default=str), axis=1)

    # --- ЭТАП 3: СОХРАНЕНИЕ ---
    try:
        df_save.to_sql('operations', engine, if_exists='append', index=False, method='multi', chunksize=1000)
    except Exception:
        pass  # Игнорируем дубликаты

    # --- ЭТАП 4: ОТВЕТ ---
    forecast = make_simple_forecast(df_save)

    return {
        "status": "success",
        "loaded": len(df_save),
        "forecast": forecast
    }


import pandas as pd
import numpy as np
import requests
from flask import Flask, request, jsonify
from statsmodels.tsa.statespace.sarimax import SARIMAX
from datetime import datetime
import warnings

warnings.filterwarnings("ignore")

app = Flask(__name__)

SARIMAX_ORDER = (1, 1, 1)
USE_SEASONAL = False
SEASONAL_ORDER = (1, 0, 1, 12)

WB_REPORT_URL = "https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod"

def fetch_wb_sales(wb_token: str, date_from: str, date_to: str) -> pd.DataFrame:
    headers = {"Authorization": wb_token}
    all_rows = []
    rrdid = 0
    limit = 100000

    while True:
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "limit": limit,
            "rrdid": rrdid
        }
        resp = requests.get(WB_REPORT_URL, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        chunk = resp.json()
        if not chunk:
            break
        all_rows.extend(chunk)
        rrdid = chunk[-1]["rrd_id"]

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    return df

def build_monthly_series(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    g["sale_dt"] = pd.to_datetime(g["sale_dt"])
    g["month"] = g["sale_dt"].dt.to_period("M").dt.to_timestamp()

    monthly = g.groupby("month").agg(
        quantity=("quantity", "sum"),
        retail_price=("retail_price", "mean"),
        retail_amount=("retail_amount", "mean"),
        commission_percent=("commission_percent", "mean"),
    ).sort_index()
    return monthly

def forecast_sarimax_monthly(monthly: pd.DataFrame, horizon_days: int) -> float:
    if monthly.empty or len(monthly) < 6:
        avg = monthly["quantity"].mean() if not monthly.empty else 0
        return max(avg / 30.0 * horizon_days, 0)

    monthly = monthly.copy()
    monthly["price_lag1"] = monthly["retail_price"].shift(1)
    monthly = monthly.dropna()
    if monthly.empty:
        return 0.0

    y = monthly["quantity"]
    exog_cols = ["retail_price", "retail_amount", "commission_percent", "price_lag1"]
    X = monthly[exog_cols]

    seasonal_order = SEASONAL_ORDER if USE_SEASONAL else (0, 0, 0, 0)

    try:
        model = SARIMAX(
            endog=y,
            exog=X,
            order=SARIMAX_ORDER,
            seasonal_order=seasonal_order,
            enforce_stationarity=False,
            enforce_invertibility=False,
        )
        res = model.fit(disp=False)
        last_exog = X.iloc[-1:].values
        fc = res.get_forecast(steps=1, exog=last_exog)
        monthly_pred = float(fc.predicted_mean.iloc[0])
        avg_per_day = monthly_pred / 30.0
        return max(avg_per_day * horizon_days, 0)
    except Exception:
        avg = y.mean()
        return max(avg / 30.0 * horizon_days, 0)

@app.route("/load_and_predict_sarimax", methods=["POST"])
def load_and_predict_sarimax():
    payload = request.get_json()

    wb_token = payload.get("wb_api_key")       # из ячейки A2
    date_from = payload.get("date_from")       # A4
    date_to = payload.get("date_to")           # A6
    clusters_config = payload.get("clusters_config", {})

    if not wb_token or not date_from or not date_to:
        return jsonify({"error": "wb_api_key, date_from, date_to are required"}), 400

    # 1. Загружаем сырые продажи из WB
    df_raw = fetch_wb_sales(wb_token, date_from, date_to)
    if df_raw.empty:
        return jsonify({"forecast_details": [], "monthly_history": [], "table_name": None})

    # 2. Оставляем только продажи, маппим поля под ваш SARIMAX
    # поля `nm_id`, `ppvz_office_id`, `retail_price`, `retail_amount`, `commission_percent` есть в отчете[web:17]
    df = df_raw.copy()
    df = df[df["supplier_oper_name"] == "Продажа"]

    # переименуем дату и количество
    df["sale_dt"] = pd.to_datetime(df["date"])
    df["quantity"] = df["quantity"]  # в отчете уже количество; поправьте, если другое поле[web:17]

    # здесь нужно добавить кластеризацию по пунктам выдачи.
    # предположим, что у вас есть таблица соответствия ppvz_office_id -> cluster_name
    # и вы уже залили ее в PostgreSQL, либо "захардкодили" в словарь.

    # пример через словарь:
    cluster_map = {
        # "office_id": "Центральный",
        # ...
    }
    df["cluster_name"] = df["ppvz_office_id"].map(cluster_map)
    df = df[~df["cluster_name"].isna()]

    if df.empty:
        return jsonify({"forecast_details": [], "monthly_history": [], "table_name": None})

    # 3. Группируем и считаем прогнозы
    grouped = df.groupby(["nm_id", "cluster_name"])

    forecast_details = []
    monthly_history = []

    for (nm_id, cluster), g in grouped:
        monthly = build_monthly_series(g)
        if monthly.empty:
            continue

        for idx, row in monthly.iterrows():
            monthly_history.append({
                "nm_id": int(nm_id),
                "cluster": cluster,
                "month": idx.strftime("%Y-%m"),
                "quantity": float(row["quantity"]),
                "retail_price": float(row["retail_price"] or 0),
                "retail_amount": float(row["retail_amount"] or 0),
                "commission_percent": float(row["commission_percent"] or 0),
            })

        horizon_days = int(clusters_config.get(cluster, 30))
        fc_val = forecast_sarimax_monthly(monthly, horizon_days)

        forecast_details.append({
            "nm_id": int(nm_id),
            "cluster": cluster,
            "forecast": float(fc_val),
            "horizon_days": horizon_days,
            "model_success": True
        })

    table_name = f"sarimax_wb_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    return jsonify({
        "forecast_details": forecast_details,
        "monthly_history": monthly_history,
        "table_name": table_name
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)





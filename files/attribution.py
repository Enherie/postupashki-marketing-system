"""
attribution.py — та же логика, что мы обкатали в отдельном скрипте на
base.xlsx, только теперь источник данных — живая БД, а не CSV.

Модель по умолчанию: last_touch с окном ATTRIBUTION_WINDOW_DAYS. Если
у заказа нет ни одного touch в окне — он уходит в 'organic/unknown'
(это ЧЕСТНО: заказы без источника не подгоняются под ближайшую кампанию).
"""
import pandas as pd

from db import get_conn

ATTRIBUTION_WINDOW_DAYS = 7


def _load_frames(db_path):
    with get_conn(db_path) as conn:
        orders = pd.read_sql("SELECT * FROM orders", conn, parse_dates=["order_time"])
        touches = pd.read_sql("SELECT * FROM touches", conn, parse_dates=["touch_time"])
        ad_links = pd.read_sql("SELECT * FROM ad_links", conn, parse_dates=["created_at"])
    return orders, touches, ad_links


def attribute_orders(db_path, window_days=ATTRIBUTION_WINDOW_DAYS):
    """Возвращает orders с добавленной колонкой ad_link_code (None = organic)."""
    orders, touches, _ = _load_frames(db_path)
    if orders.empty:
        orders["ad_link_code"] = []
        return orders

    result = []
    for order in orders.itertuples():
        if order.user_id is None:
            result.append(None)
            continue
        window_start = order.order_time - pd.Timedelta(days=window_days)
        cand = touches[
            (touches.user_id == order.user_id)
            & (touches.touch_time <= order.order_time)
            & (touches.touch_time >= window_start)
        ]
        if cand.empty:
            result.append(None)
        else:
            result.append(cand.sort_values("touch_time").iloc[-1].ad_link_code)
    orders = orders.copy()
    orders["ad_link_code"] = result
    return orders


def romi_by_link(db_path, window_days=ATTRIBUTION_WINDOW_DAYS):
    orders, touches, ad_links = _load_frames(db_path)
    attributed = attribute_orders(db_path, window_days)

    click_counts = touches.groupby("ad_link_code").size().rename("clicks")
    rev = (
        attributed[attributed.ad_link_code.notna()]
        .groupby("ad_link_code")["amount"]
        .sum()
        .rename("attributed_revenue")
    )
    buyers = (
        attributed[attributed.ad_link_code.notna()]
        .groupby("ad_link_code")["user_id"]
        .nunique()
        .rename("buyers")
    )

    report = ad_links.set_index("code")[["channel", "placement", "cost"]]
    report = report.join(click_counts).join(rev).join(buyers).fillna(0)
    report["ROMI"] = report.apply(
        lambda r: (r.attributed_revenue - r.cost) / r.cost if r.cost > 0 else float("nan"), axis=1
    )
    return report.sort_values("ROMI", ascending=False).reset_index()


def funnel_summary(db_path, window_days=ATTRIBUTION_WINDOW_DAYS):
    orders = attribute_orders(db_path, window_days)
    total_orders = len(orders)
    total_revenue = orders["amount"].sum() if total_orders else 0
    organic_orders = int(orders["ad_link_code"].isna().sum()) if total_orders else 0
    attributed_revenue = orders.loc[orders.ad_link_code.notna(), "amount"].sum() if total_orders else 0
    return dict(
        total_orders=total_orders,
        total_revenue=total_revenue,
        organic_orders=organic_orders,
        organic_share=(organic_orders / total_orders) if total_orders else 0,
        attributed_revenue=attributed_revenue,
    )

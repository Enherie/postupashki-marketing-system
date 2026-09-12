"""
tests/test_core.py — тесты db/attribution/importer БЕЗ Telegram.
Запуск: python tests/test_core.py

Это то, что реально можно прогнать в CI/при ревью — сама отправка
сообщений в Telegram здесь не тестируется (для этого нужен живой бот).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import importer
import attribution

TEST_DB = os.path.join(os.path.dirname(__file__), "_test.db")

_failures = []


def check(name, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        _failures.append(name)


def fresh_db():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db.init_db(TEST_DB)


def test_users_and_links():
    fresh_db()
    check("новый пользователь -> True", db.upsert_user(TEST_DB, 1, "a", "A") is True)
    check("повторный upsert -> False", db.upsert_user(TEST_DB, 1, "a", "A") is False)

    db.create_ad_link(TEST_DB, "l1", "Channel A", "post", "cr1", 15000)
    link = db.get_ad_link(TEST_DB, "l1")
    check("ad_link создан и читается", link is not None and link["cost"] == 15000)


def test_attribution_last_touch():
    fresh_db()
    db.create_ad_link(TEST_DB, "l1", "Channel A", "post", "cr1", 10000)
    db.create_ad_link(TEST_DB, "l2", "Channel B", "post", "cr2", 5000)
    for uid in (1, 2, 3):
        db.upsert_user(TEST_DB, uid, f"u{uid}", f"U{uid}")

    db.add_touch(TEST_DB, 1, "l1", "deeplink")
    db.add_order(TEST_DB, 1, "Курс А", 6900)

    db.add_touch(TEST_DB, 2, "l2", "promo")
    db.add_order(TEST_DB, 2, "Курс Б", 7900)

    db.add_order(TEST_DB, 3, "Курс В", 5000)  # без touch -> organic

    attributed = attribution.attribute_orders(TEST_DB)
    by_user = attributed.set_index("user_id")["ad_link_code"]
    check("заказ user1 атрибутирован на l1", by_user.loc[1] == "l1")
    check("заказ user2 атрибутирован на l2", by_user.loc[2] == "l2")
    check("заказ user3 organic (нет touch)", by_user.loc[3] is None or str(by_user.loc[3]) == "nan")

    summary = attribution.funnel_summary(TEST_DB)
    check("funnel_summary: 1 organic из 3", summary["organic_orders"] == 1)

    romi = attribution.romi_by_link(TEST_DB)
    l1_romi = romi.set_index("code").loc["l1", "ROMI"]
    check("ROMI l1 = (6900-10000)/10000", abs(l1_romi - (6900 - 10000) / 10000) < 1e-6)


def test_attribution_window():
    """Touch за пределами окна не должен атрибутироваться."""
    fresh_db()
    db.create_ad_link(TEST_DB, "l1", "Channel A", "post", "cr1", 1000)
    db.upsert_user(TEST_DB, 1, "a", "A")
    with db.get_conn(TEST_DB) as conn:
        conn.execute(
            "INSERT INTO touches (user_id, ad_link_code, source, touch_time) VALUES (?,?,?,?)",
            (1, "l1", "deeplink", "2026-01-01 00:00:00"),
        )
        conn.execute(
            "INSERT INTO orders (user_id, course, amount, order_time, source) VALUES (?,?,?,?,?)",
            (1, "Курс", 5000, "2026-02-01 00:00:00", "bot"),  # 31 день спустя, окно = 7 дней
        )
    attributed = attribution.attribute_orders(TEST_DB, window_days=7)
    check("touch за пределами окна не атрибутируется", attributed.iloc[0]["ad_link_code"] is None)


def test_promo_dedupe():
    fresh_db()
    db.create_ad_link(TEST_DB, "l1", "Channel A", "post", "cr1", 1000)
    db.upsert_user(TEST_DB, 1, "a", "A")
    db.add_touch(TEST_DB, 1, "l1", "promo", dedupe=True)
    db.add_touch(TEST_DB, 1, "l1", "promo", dedupe=True)  # повторный ввод того же промокода
    with db.get_conn(TEST_DB) as conn:
        n = conn.execute("SELECT COUNT(*) FROM touches WHERE user_id=1").fetchone()[0]
    check("dedupe=True не плодит повторные touch", n == 1)


def test_importer_default_columns():
    fresh_db()
    base_path = os.path.join(os.path.dirname(__file__), "..", "data", "base.xlsx")
    if not os.path.exists(base_path):
        print("  (пропущено: data/base.xlsx не найден рядом с проектом)")
        return
    n_rows, n_users = importer.import_sales_table(TEST_DB, base_path)
    check("импорт base.xlsx дал строки", n_rows > 0)
    summary = attribution.funnel_summary(TEST_DB)
    check("все импортированные заказы organic (нет touch-данных)", summary["organic_share"] == 1.0)


def test_importer_custom_columns():
    import pandas as pd
    fresh_db()
    tmp_csv = os.path.join(os.path.dirname(__file__), "_other_shop.csv")
    pd.DataFrame({
        "customer_id": ["a1", "a2"],
        "price": [1000, 2000],
        "product": ["X", "Y"],
        "purchased_at": ["2026-01-01 10:00:00", "2026-01-02 11:00:00"],
    }).to_csv(tmp_csv, index=False)
    n_rows, n_users = importer.import_sales_table(
        TEST_DB, tmp_csv,
        student_col="customer_id", amount_col="price", course_col="product", time_col="purchased_at",
    )
    check("импорт таблицы с другими колонками сработал", n_rows == 2 and n_users == 2)
    os.remove(tmp_csv)


if __name__ == "__main__":
    test_users_and_links()
    test_attribution_last_touch()
    test_attribution_window()
    test_promo_dedupe()
    test_importer_default_columns()
    test_importer_custom_columns()

    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    print()
    if _failures:
        print(f"=== FAILED: {_failures} ===")
        sys.exit(1)
    print("=== ALL TESTS PASSED ===")

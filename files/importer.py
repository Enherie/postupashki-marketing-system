"""
importer.py — заливает ЛЮБУЮ табличку продаж (не только base.xlsx) в ту же
БД, что использует бот. Колонки настраиваются, поэтому под другую таблицу
достаточно поменять 4 имени колонок, а не переписывать код.

Импортированные заказы всегда попадают в 'organic/unknown' в attribution —
это честно: у исторических продаж нет данных о касаниях, и подделывать
их не нужно.
"""
import pandas as pd

from db import get_conn, now_iso


def import_sales_table(
    db_path,
    file_path,
    student_col="Номер студента",
    amount_col="Сумма",
    course_col="Курс",
    time_col="Время",
    sheet_name=0,
):
    """Возвращает (n_rows, n_new_users)."""
    if str(file_path).lower().endswith(".csv"):
        df = pd.read_csv(file_path)
    else:
        df = pd.read_excel(file_path, sheet_name=sheet_name)

    missing = [c for c in (student_col, amount_col, course_col, time_col) if c not in df.columns]
    if missing:
        raise ValueError(
            f"В файле нет колонок {missing}. Есть колонки: {list(df.columns)}. "
            f"Передайте правильные имена через student_col/amount_col/course_col/time_col."
        )

    df = df.rename(columns={
        student_col: "student_id", amount_col: "amount",
        course_col: "course", time_col: "ts",
    })
    df["ts"] = pd.to_datetime(df["ts"])

    n_new_users = 0
    with get_conn(db_path) as conn:
        existing_users = {r[0] for r in conn.execute("SELECT user_id FROM users")}
        for row in df.itertuples():
            uid = int(row.student_id) if str(row.student_id).isdigit() else hash(row.student_id) % (10**9)
            if uid not in existing_users:
                conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at) VALUES (?,?,?,?)",
                    (uid, None, None, now_iso()),
                )
                existing_users.add(uid)
                n_new_users += 1
            conn.execute(
                "INSERT INTO orders (user_id, course, amount, promo_code, order_time, source) "
                "VALUES (?,?,?,?,?,'import')",
                (uid, row.course, float(row.amount), None, row.ts.strftime("%Y-%m-%d %H:%M:%S")),
            )

    return len(df), n_new_users

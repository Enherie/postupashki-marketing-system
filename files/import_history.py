"""
import_history.py — разовая заливка исторических продаж в базу бота,
без необходимости слать файл в чат. Полезно на старте, чтобы прогноз
и общая статистика сразу видели прошлое, а не только новых пользователей.

Примеры:
    python import_history.py data/base.xlsx
    python import_history.py other_shop.csv --student-col customer_id \\
        --amount-col price --course-col product --time-col purchased_at
"""
import argparse

import config
import db
import importer


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", help="путь к .xlsx или .csv с историческими продажами")
    ap.add_argument("--student-col", default="Номер студента")
    ap.add_argument("--amount-col", default="Сумма")
    ap.add_argument("--course-col", default="Курс")
    ap.add_argument("--time-col", default="Время")
    args = ap.parse_args()

    db.init_db(config.DB_PATH)
    n_rows, n_users = importer.import_sales_table(
        config.DB_PATH, args.file,
        student_col=args.student_col, amount_col=args.amount_col,
        course_col=args.course_col, time_col=args.time_col,
    )
    print(f"Импортировано {n_rows} заказов, новых пользователей: {n_users}.")
    print(f"База: {config.DB_PATH}")


if __name__ == "__main__":
    main()

"""
admin.py — "панель управления", реализованная как admin-only команды
в том же боте, а не отдельный сайт: метрики там же, где сидит владелец
бизнеса весь день. Все команды доступны только id из config.ADMIN_IDS.
"""
import os
import uuid

import pandas as pd

import attribution
import config
import db
import importer


def _is_admin(message):
    return message.from_user.id in config.ADMIN_IDS


def _deny(bot, message):
    bot.reply_to(message, "Команда только для администраторов.")


def register_admin_handlers(bot):

    @bot.message_handler(commands=["newlink"])
    def newlink(message):
        if not _is_admin(message):
            return _deny(bot, message)
        raw = message.text.split(maxsplit=1)
        if len(raw) < 2:
            bot.reply_to(message,
                         "Формат: /newlink Канал А | 25000 | native_post | creative1 | комментарий\n"
                         "(канал и стоимость обязательны, остальное опционально)")
            return
        parts = [p.strip() for p in raw[1].split("|")]
        channel = parts[0] if len(parts) > 0 else ""
        try:
            cost = float(parts[1]) if len(parts) > 1 else 0.0
        except ValueError:
            bot.reply_to(message, "Стоимость должна быть числом.")
            return
        placement = parts[2] if len(parts) > 2 else "-"
        creative = parts[3] if len(parts) > 3 else "-"
        comment = parts[4] if len(parts) > 4 else ""

        code = "l" + uuid.uuid4().hex[:6]
        db.create_ad_link(config.DB_PATH, code, channel, placement, creative, cost, comment)
        link = f"https://t.me/{config.BOT_USERNAME}?start={code}"
        bot.reply_to(
            message,
            f"Создано размещение <code>{code}</code>\nКанал: {channel} | Cost: {cost:,.0f} \u20bd\n"
            f"Ссылка для рекламы:\n{link}".replace(",", " "),
        )

    @bot.message_handler(commands=["links"])
    def links(message):
        if not _is_admin(message):
            return _deny(bot, message)
        rows = db.list_ad_links(config.DB_PATH)
        if not rows:
            bot.reply_to(message, "Пока нет ни одного размещения. Создайте: /newlink")
            return
        lines = []
        for r in rows:
            link = f"https://t.me/{config.BOT_USERNAME}?start={r['code']}"
            lines.append(f"<code>{r['code']}</code> — {r['channel']} ({r['cost']:,.0f} \u20bd)\n{link}"
                         .replace(",", " "))
        bot.reply_to(message, "\n\n".join(lines))

    @bot.message_handler(commands=["newpromo"])
    def newpromo(message):
        if not _is_admin(message):
            return _deny(bot, message)
        parts = message.text.split()[1:]
        if len(parts) < 2:
            bot.reply_to(message, "Формат: /newpromo КОД СКИДКА_% [код_ссылки]")
            return
        code, discount = parts[0].upper(), parts[1]
        ad_link_code = parts[2] if len(parts) > 2 else None
        try:
            discount = float(discount)
        except ValueError:
            bot.reply_to(message, "Скидка должна быть числом (процент).")
            return
        if ad_link_code and not db.get_ad_link(config.DB_PATH, ad_link_code):
            bot.reply_to(message, f"Размещения с кодом {ad_link_code} не существует.")
            return
        db.create_promocode(config.DB_PATH, code, discount, ad_link_code)
        tie = f" (привязан к {ad_link_code})" if ad_link_code else ""
        bot.reply_to(message, f"Промокод {code} создан: скидка {discount:.0f}%{tie}")

    @bot.message_handler(commands=["stats"])
    def stats(message):
        if not _is_admin(message):
            return _deny(bot, message)
        c = db.counts(config.DB_PATH)
        f = attribution.funnel_summary(config.DB_PATH)
        text = (
            f"Пользователей: {c['users']}\n"
            f"Касаний: {c['touches']}\n"
            f"Заказов: {c['orders']} на {c['revenue']:,.0f} \u20bd\n"
            f"Из них без источника (organic/unknown): {f['organic_orders']} "
            f"({f['organic_share']:.0%})\n"
            f"Атрибутированная выручка: {f['attributed_revenue']:,.0f} \u20bd"
        ).replace(",", " ")
        bot.reply_to(message, text)

    @bot.message_handler(commands=["romi"])
    def romi(message):
        if not _is_admin(message):
            return _deny(bot, message)
        report = attribution.romi_by_link(config.DB_PATH)
        if report.empty:
            bot.reply_to(message, "Пока нет размещений с касаниями.")
            return
        lines = []
        for r in report.itertuples():
            romi_str = f"{r.ROMI:+.0%}" if pd.notna(r.ROMI) else "н/д (cost=0)"
            lines.append(
                f"<code>{r.code}</code> {r.channel}: клики={int(r.clicks)}, "
                f"покупатели={int(r.buyers)}, выручка={r.attributed_revenue:,.0f} \u20bd, "
                f"cost={r.cost:,.0f} \u20bd, ROMI={romi_str}".replace(",", " ")
            )
        bot.reply_to(message, "\n".join(lines))

    @bot.message_handler(commands=["forecast"])
    def forecast(message):
        if not _is_admin(message):
            return _deny(bot, message)
        with db.get_conn(config.DB_PATH) as conn:
            orders = pd.read_sql("SELECT amount, order_time FROM orders", conn, parse_dates=["order_time"])
        if orders.empty:
            bot.reply_to(message, "Нет заказов для прогноза.")
            return
        orders["date"] = orders["order_time"].dt.date
        daily = orders.groupby("date")["amount"].sum()
        full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D").date
        daily = daily.reindex(full_range, fill_value=0.0)

        if len(daily) < 14:
            bot.reply_to(message, f"Истории всего {len(daily)} дн. — маловато для честного backtest "
                                   f"(нужно хотя бы 2 недели).")
            return

        test_days = min(7, len(daily) // 3)
        test = daily.iloc[-test_days:]
        errors = {"naive": [], "seasonal_naive": [], "moving_avg_7": []}
        for d in test.index:
            actual = daily.loc[d]
            naive_pred = daily.get(d - pd.Timedelta(days=1), pd.NA)
            seasonal_pred = daily.get(d - pd.Timedelta(days=7), pd.NA)
            window = daily.loc[d - pd.Timedelta(days=7): d - pd.Timedelta(days=1)]
            ma_pred = window.mean() if len(window) else pd.NA
            for name, pred in [("naive", naive_pred), ("seasonal_naive", seasonal_pred), ("moving_avg_7", ma_pred)]:
                if pd.notna(pred):
                    errors[name].append(abs(actual - pred))

        lines = [f"Истории: {len(daily)} дн. Backtest на последних {test_days} дн.:"]
        for name, errs in errors.items():
            if errs:
                mae = sum(errs) / len(errs)
                lines.append(f"  {name}: MAE = {mae:,.0f} \u20bd/день".replace(",", " "))
        bot.reply_to(message, "\n".join(lines))

    @bot.message_handler(content_types=["document"])
    def import_document(message):
        if not _is_admin(message):
            return  # молча игнорируем документы от не-админов
        file_name = message.document.file_name or ""
        if not (file_name.endswith(".xlsx") or file_name.endswith(".csv")):
            bot.reply_to(message, "Поддерживаются только .xlsx и .csv.")
            return
        file_info = bot.get_file(message.document.file_id)
        content = bot.download_file(file_info.file_path)
        tmp_path = os.path.join("data", f"_upload_{uuid.uuid4().hex[:8]}_{file_name}")
        os.makedirs("data", exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(content)
        try:
            n_rows, n_users = importer.import_sales_table(config.DB_PATH, tmp_path)
            bot.reply_to(message, f"Импортировано {n_rows} строк, новых пользователей: {n_users}.")
        except ValueError as e:
            bot.reply_to(
                message,
                f"Не смог импортировать: {e}\n\n"
                f"Если у файла другие названия колонок — запустите импорт локально через "
                f"importer.import_sales_table(...) с параметрами student_col/amount_col/course_col/time_col.",
            )
        finally:
            os.remove(tmp_path)

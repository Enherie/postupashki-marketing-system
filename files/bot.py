"""
bot.py — пользовательская часть. Всё, что касается измерения
(касания/атрибуция/ROMI), физически находится в db.py и attribution.py —
здесь только сценарий диалога.

ВАЖНО: оплата — ДЕМО. Кнопка "Оплатить" сразу пишет заказ в БД, без
реальной интеграции с платёжным провайдером. Для продакшна сюда
встраивается Telegram Payments API / любой эквайринг, сам факт записи
заказа в orders останется тем же.
"""
import logging

import telebot

import config
import db
import keyboards as kb
from admin import register_admin_handlers

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")

# Эфемерное состояние UI (не бизнес-данные, поэтому просто в памяти).
_awaiting_promo = set()


def _user_active_promo(user_id):
    with db.get_conn(config.DB_PATH) as conn:
        row = conn.execute("SELECT promo_code FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row["promo_code"] if row else None


@bot.message_handler(commands=["start"])
def handle_start(message):
    parts = message.text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else None

    is_new = db.upsert_user(
        config.DB_PATH, message.from_user.id, message.from_user.username, message.from_user.first_name
    )

    if payload:
        ad_link = db.get_ad_link(config.DB_PATH, payload)
        if ad_link:
            db.add_touch(config.DB_PATH, message.from_user.id, payload, source="deeplink")
            log.info("touch: user=%s via ad_link=%s", message.from_user.id, payload)

    greeting = "С возвращением!" if not is_new else "Привет! Это Поступашки."
    bot.send_message(
        message.chat.id,
        f"{greeting}\nЗдесь можно посмотреть курсы и активировать промокод.",
        reply_markup=kb.main_menu(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "menu:main")
def cb_main(call):
    bot.edit_message_text("Главное меню:", call.message.chat.id, call.message.message_id,
                           reply_markup=kb.main_menu())


@bot.callback_query_handler(func=lambda call: call.data == "menu:catalog")
def cb_catalog(call):
    bot.edit_message_text("Выберите направление:", call.message.chat.id, call.message.message_id,
                           reply_markup=kb.catalog_menu())


@bot.callback_query_handler(func=lambda call: call.data.startswith("course:"))
def cb_course(call):
    course_key = call.data.split(":", 1)[1]
    title = config.COURSES[course_key]["title"]
    bot.edit_message_text(f"{title} — выберите тариф:", call.message.chat.id, call.message.message_id,
                           reply_markup=kb.tier_menu(course_key))


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy:"))
def cb_buy(call):
    _, course_key, tier_key = call.data.split(":")
    price = config.course_price(course_key, tier_key)
    name = config.course_full_name(course_key, tier_key)

    promo = _user_active_promo(call.from_user.id)
    final_price = price
    note = ""
    if promo:
        promocode = db.get_promocode(config.DB_PATH, promo)
        if promocode:
            final_price = round(price * (1 - promocode["discount_percent"] / 100))
            note = f"\nПромокод {promo}: скидка {promocode['discount_percent']:.0f}%"

    text = f"<b>{name}</b>\nЦена: {final_price:,} \u20bd{note}".replace(",", " ")
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                           reply_markup=kb.confirm_purchase_menu(course_key, tier_key))


@bot.callback_query_handler(func=lambda call: call.data.startswith("pay:"))
def cb_pay(call):
    _, course_key, tier_key = call.data.split(":")
    price = config.course_price(course_key, tier_key)
    name = config.course_full_name(course_key, tier_key)

    promo = _user_active_promo(call.from_user.id)
    final_price = price
    if promo and db.get_promocode(config.DB_PATH, promo):
        discount = db.get_promocode(config.DB_PATH, promo)["discount_percent"]
        final_price = round(price * (1 - discount / 100))

    db.add_order(config.DB_PATH, call.from_user.id, name, final_price, promo_code=promo, source="bot")
    bot.edit_message_text(
        f"Готово (демо-оплата)! {name} — {final_price:,} \u20bd.\nСпасибо за покупку!".replace(",", " "),
        call.message.chat.id, call.message.message_id, reply_markup=kb.main_menu(),
    )


@bot.callback_query_handler(func=lambda call: call.data == "menu:promo")
def cb_promo(call):
    _awaiting_promo.add(call.from_user.id)
    bot.edit_message_text("Введите промокод сообщением:", call.message.chat.id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "menu:my_orders")
def cb_my_orders(call):
    with db.get_conn(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT course, amount, order_time FROM orders WHERE user_id=? ORDER BY order_time DESC",
            (call.from_user.id,),
        ).fetchall()
    if not rows:
        text = "Пока нет покупок."
    else:
        lines = [f"\u2022 {r['course']} — {r['amount']:,.0f} \u20bd ({r['order_time'][:10]})".replace(",", " ")
                 for r in rows]
        text = "Ваши покупки:\n" + "\n".join(lines)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb.main_menu())


@bot.message_handler(func=lambda message: message.from_user.id in _awaiting_promo, content_types=["text"])
def handle_promo_text(message):
    _awaiting_promo.discard(message.from_user.id)
    code = message.text.strip().upper()
    promocode = db.get_promocode(config.DB_PATH, code)
    if not promocode:
        bot.send_message(message.chat.id, "Такой промокод не найден.", reply_markup=kb.main_menu())
        return

    db.set_user_promo(config.DB_PATH, message.from_user.id, code)
    if promocode["ad_link_code"]:
        db.add_touch(config.DB_PATH, message.from_user.id, promocode["ad_link_code"], source="promo", dedupe=True)

    bot.send_message(
        message.chat.id,
        f"Промокод {code} активирован: скидка {promocode['discount_percent']:.0f}% на следующую покупку.",
        reply_markup=kb.main_menu(),
    )


if __name__ == "__main__":
    db.init_db(config.DB_PATH)
    register_admin_handlers(bot)
    log.info("Bot started, polling...")
    bot.infinity_polling()

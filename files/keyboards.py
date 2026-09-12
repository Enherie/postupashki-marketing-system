"""
keyboards.py — вся разметка inline-кнопок в одном месте, чтобы bot.py
и admin.py оставались читаемыми. Стиль сознательно минималистичный:
без эмодзи-шума, короткие подписи, максимум 2 колонки.
"""
from telebot import types

from config import COURSES, course_full_name, course_price


def main_menu():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("Каталог курсов", callback_data="menu:catalog"),
        types.InlineKeyboardButton("У меня есть промокод", callback_data="menu:promo"),
        types.InlineKeyboardButton("Мои покупки", callback_data="menu:my_orders"),
    )
    return kb


def catalog_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton(c["title"], callback_data=f"course:{key}")
        for key, c in COURSES.items()
    ]
    kb.add(*buttons)
    kb.add(types.InlineKeyboardButton("‹ Назад", callback_data="menu:main"))
    return kb


def tier_menu(course_key):
    course = COURSES[course_key]
    kb = types.InlineKeyboardMarkup(row_width=1)
    for tier_key, price in course["tiers"].items():
        name = course_full_name(course_key, tier_key)
        kb.add(types.InlineKeyboardButton(f"{name} — {price:,} \u20bd".replace(",", " "),
                                           callback_data=f"buy:{course_key}:{tier_key}"))
    kb.add(types.InlineKeyboardButton("‹ К каталогу", callback_data="menu:catalog"))
    return kb


def confirm_purchase_menu(course_key, tier_key):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("Оплатить (демо)", callback_data=f"pay:{course_key}:{tier_key}"),
        types.InlineKeyboardButton("‹ Отмена", callback_data="menu:catalog"),
    )
    return kb

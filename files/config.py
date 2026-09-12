"""
config.py — все настройки в одном месте. Токен НИКОГДА не хранится
в коде — только в локальном .env (см. .env.example), который в
.gitignore и не попадает в репозиторий.
"""
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8402875149:AAHIczm2lj1W1RiDm4wh6fvupxRrWwarYGg")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "postypashki_test_bot")

# Telegram user_id админов через запятую в .env: ADMIN_IDS=123456,789012
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()}

DB_PATH = os.environ.get("DB_PATH", "data/bot.db")

ATTRIBUTION_WINDOW_DAYS = 7

# Каталог курсов. 5 направлений с двумя тарифами (Старт/Про) + 4 курса
# без деления на тарифы. Цены демонстрационные — поправьте под реальные.
COURSES = {
    "ai_agents":     {"title": "AI агенты",     "tiers": {"старт": 6900, "про": 9900}},
    "algorithms":    {"title": "Алгоритмы",     "tiers": {"старт": 6900, "про": 9900}},
    "analytics":     {"title": "Аналитика",     "tiers": {"старт": 6900, "про": 9900}},
    "ml":            {"title": "ML",            "tiers": {"старт": 6900, "про": 9900}},
    "backend":       {"title": "Backend",       "tiers": {"старт": 6900, "про": 9900}},
    "ab_tests":      {"title": "А/Б тесты",     "tiers": {"база": 7500}},
    "data_science":  {"title": "Data Science",  "tiers": {"база": 7900}},
    "data_engineer": {"title": "Data Инженер",  "tiers": {"база": 7900}},
    "frontend":      {"title": "Фронтенд",      "tiers": {"база": 7500}},
}


def course_full_name(course_key, tier_key):
    course = COURSES[course_key]
    if tier_key == "база":
        return course["title"]
    # без .capitalize() специально: в исторических данных (base.xlsx)
    # тариф пишется с маленькой буквы — "ML старт", "Алгоритмы про" —
    # сохраняем то же написание, чтобы отчётность не разъезжалась
    # на "ML старт" и "ML Старт" как на два разных курса.
    return f"{course['title']} {tier_key}"


def course_price(course_key, tier_key):
    return COURSES[course_key]["tiers"][tier_key]

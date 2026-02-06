import os
import math
import asyncio
from typing import Dict, Any, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Получаем токен из переменной окружения Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден. Добавь его в Environment Variables в Render.")
PRODUCTS: Dict[str, Dict[str, Any]] = {
    "film_60x3": {
        "title": "Плёнка 60×3 м (рулон)",
        "pack_area": 0.6 * 3.0,  # 1.8 м²
        "pack_name": "рулон(ов)",
    },
    "panel_30x30_20": {
        "title": "Панели 30×30 см (20 шт/уп)",
        "pack_area": 0.3 * 0.3 * 20,  # 1.8 м²
        "pack_name": "упаковок",
    },
    "panel_30x60_auto": {
        "title": "Панели 30×60 см (автоподбор 10 или 18 шт/уп)",
        "auto_pick": True,
        "variants": [
            {"label": "10 шт/уп", "pack_area": 0.3 * 0.6 * 10, "pack_name": "упаковок"},
            {"label": "18 шт/уп", "pack_area": 0.3 * 0.6 * 18, "pack_name": "упаковок"},
        ],
    },
    "all_products": {
        "title": "Рассчитать все товары сразу",
        "all": True,
    }
}


class CalcState(StatesGroup):
    choose_input_mode = State()
    waiting_total_area = State()

    waiting_surface_name = State()
    waiting_surface_length = State()
    waiting_surface_width = State()
    waiting_surface_sides = State()

    waiting_ask_price = State()
    waiting_price_single = State()

    waiting_price_all_film = State()
    waiting_price_all_30x30 = State()
    waiting_price_all_30x60_10 = State()
    waiting_price_all_30x60_18 = State()


dp = Dispatcher()


def welcome_text() -> str:
    return (
        "✨ the_all4u — самоклеящиеся покрытия\n\n"
        "Не знаете, сколько материала нужно?\n"
        "Я рассчитаю всё за вас:\n\n"
        "✔ плёнка 60 см *3м\n"
        "✔ панели 30×30 см\n"
        "✔ панели 30×60 см\n"
        "✔ автоматический подбор упаковок\n"
        "✔ запас 10%\n"
        "✔ расчёт стоимости в ₽\n\n"
        "Выберите вариант расчёта и получите точный результат 👌"
    )


def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="1) Плёнка 60×3 м", callback_data="calc:film_60x3")
    kb.button(text="2) Панели 30×30 (20 шт/уп)", callback_data="calc:panel_30x30_20")
    kb.button(text="3) Панели 30×60 (автоподбор)", callback_data="calc:panel_30x60_auto")
    kb.button(text="4) Рассчитать все товары", callback_data="calc:all_products")
    kb.adjust(1)
    return kb.as_markup()


def input_mode_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Быстрый ввод общей площади (м²)", callback_data="mode:total")
    kb.button(text="Добавить поверхности (мебель/полки/стол)", callback_data="mode:surfaces")
    kb.button(text="⬅ Назад к выбору товара", callback_data="back:products")
    kb.adjust(1)
    return kb.as_markup()


def surfaces_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить ещё поверхность", callback_data="surface:add")
    kb.button(text="✅ Завершить и рассчитать", callback_data="surface:finish")
    kb.button(text="🗑 Очистить список", callback_data="surface:clear")
    kb.adjust(1)
    return kb.as_markup()


def sides_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="1 сторона", callback_data="sides:1")
    kb.button(text="2 стороны", callback_data="sides:2")
    kb.adjust(2)
    return kb.as_markup()


def price_choice_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Да, рассчитать стоимость", callback_data="price:yes")
    kb.button(text="➡️ Нет, только количество", callback_data="price:no")
    kb.adjust(1)
    return kb.as_markup()


def parse_float(text: str) -> float:
    v = float(text.strip().replace(",", "."))
    if v <= 0:
        raise ValueError
    return v


def with_reserve(area: float, reserve: float = 0.10) -> float:
    return area * (1 + reserve)


def packs_needed(area_with_reserve: float, pack_area: float) -> int:
    return math.ceil(area_with_reserve / pack_area)


def fmt(n: float) -> str:
    return f"{n:.2f}".rstrip("0").rstrip(".")


def money(n: float) -> str:
    return f"{n:,.2f}".replace(",", " ") + " ₽"


def calc_counts_for_product(product_key: str, area: float) -> Dict[str, Any]:
    p = PRODUCTS[product_key]
    target = with_reserve(area, 0.10)

    if p.get("auto_pick"):
        variants = []
        best = None
        best_over = None
        for v in p["variants"]:
            cnt = packs_needed(target, v["pack_area"])
            covered = cnt * v["pack_area"]
            over = covered - target
            item = {
                "label": v["label"],
                "count": cnt,
                "pack_name": v["pack_name"],
                "covered": covered,
                "over": over
            }
            variants.append(item)
            if best_over is None or over < best_over:
                best_over = over
                best = item
        return {
            "type": "auto_pick",
            "title": p["title"],
            "target_area": target,
            "variants": variants,
            "best": best
        }

    if p.get("all"):
        return {
            "type": "all",
            "target_area": target,
            "film_cnt": packs_needed(target, PRODUCTS["film_60x3"]["pack_area"]),
            "p3030_cnt": packs_needed(target, PRODUCTS["panel_30x30_20"]["pack_area"]),
            "p3060_10_cnt": packs_needed(target, 0.3 * 0.6 * 10),
            "p3060_18_cnt": packs_needed(target, 0.3 * 0.6 * 18),
        }

    cnt = packs_needed(target, p["pack_area"])
    covered = cnt * p["pack_area"]
    return {
        "type": "single",
        "title": p["title"],
        "target_area": target,
        "count": cnt,
        "pack_name": p["pack_name"],
        "covered": covered
    }


def render_counts(area: float, counts: Dict[str, Any]) -> str:
    header = (
        f"📐 Площадь: {fmt(area)} м²\n"
        f"📦 С запасом 10%: {fmt(counts['target_area'])} м²\n\n"
    )

    if counts["type"] == "single":
        return (
            header +
            f"🔹 {counts['title']}\n"
            f"Нужно: {counts['count']} {counts['pack_name']}\n"
            f"Покрытие: ~ {fmt(counts['covered'])} м²"
        )

    if counts["type"] == "auto_pick":
        lines = [header + f"🔹 {counts['title']}"]
        for v in counts["variants"]:
            lines.append(f"• {v['label']}: {v['count']} упаковок (покроет ~ {fmt(v['covered'])} м²)")
        lines.append("")
        lines.append(f"✅ Рекомендация: {counts['best']['label']} — {counts['best']['count']} упаковок")
        return "\n".join(lines)

    return (
        header +
        "📦 Расчёт по всем товарам:\n\n"
        f"1) Плёнка 60×3 м: {counts['film_cnt']} рулон(ов)\n"
        f"2) Панели 30×30 (20 шт/уп): {counts['p3030_cnt']} упаковок\n"
        f"3) Панели 30×60 (10 шт/уп): {counts['p3060_10_cnt']} упаковок\n"
        f"4) Панели 30×60 (18 шт/уп): {counts['p3060_18_cnt']} упаковок"
    )


def surfaces_total(data_surfaces: List[Dict[str, Any]]) -> float:
    return sum(item["area"] for item in data_surfaces)


def surfaces_summary(data_surfaces: List[Dict[str, Any]]) -> str:
    if not data_surfaces:
        return "Пока не добавлено ни одной поверхности."
    lines = ["Добавленные поверхности:"]
    for i, s in enumerate(data_surfaces, 1):
        sides_txt = "2 стороны" if s["sides"] == 2 else "1 сторона"
        lines.append(
            f"{i}) {s['name']}: {fmt(s['length_cm'])}×{fmt(s['width_cm'])} см, {sides_txt} = {fmt(s['area'])} м²"
        )
    lines.append(f"\nИтого: {fmt(surfaces_total(data_surfaces))} м²")
    return "\n".join(lines)


@dp.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(welcome_text(), reply_markup=main_menu_kb())


@dp.callback_query(F.data == "back:products")
async def back_products(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Выберите товар:", reply_markup=main_menu_kb())
    await callback.answer()


@dp.callback_query(F.data.startswith("calc:"))
async def choose_product(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    if key not in PRODUCTS:
        await callback.answer("Неизвестный товар", show_alert=True)
        return

    await state.update_data(product_key=key, surfaces=[])
    await state.set_state(CalcState.choose_input_mode)

    await callback.message.answer(
        f"Вы выбрали: {PRODUCTS[key]['title']}\n\nКак хотите ввести площадь?",
        reply_markup=input_mode_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "mode:total")
async def mode_total(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CalcState.waiting_total_area)
    await callback.message.answer("Введите общую площадь в м² (например: 12.5)")
    await callback.answer()


@dp.callback_query(F.data == "mode:surfaces")
async def mode_surfaces(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CalcState.waiting_surface_name)
    await callback.message.answer("Введите название поверхности (например: Стол, Полка 1, Дверца шкафа):")
    await callback.answer()


@dp.message(CalcState.waiting_total_area)
async def process_total_area(message: Message, state: FSMContext):
    try:
        area = parse_float(message.text)
    except Exception:
        await message.answer("Введите корректное число, например: 9.8")
        return

    data = await state.get_data()
    product_key = data.get("product_key", "all_products")
    counts = calc_counts_for_product(product_key, area)
    await state.update_data(last_area=area, last_counts=counts)

    await message.answer(render_counts(area, counts) + "\n\nХотите рассчитать стоимость в рублях?",
                         reply_markup=price_choice_kb())
    await state.set_state(CalcState.waiting_ask_price)


@dp.message(CalcState.waiting_surface_name)
async def surface_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Название не должно быть пустым.")
        return
    await state.update_data(current_name=name)
    await state.set_state(CalcState.waiting_surface_length)
    await message.answer("Введите длину в см (например: 120)")


@dp.message(CalcState.waiting_surface_length)
async def surface_length(message: Message, state: FSMContext):
    try:
        length_cm = parse_float(message.text)
    except Exception:
        await message.answer("Введите корректную длину в см.")
        return
    await state.update_data(current_length_cm=length_cm)
    await state.set_state(CalcState.waiting_surface_width)
    await message.answer("Введите ширину в см (например: 60)")


@dp.message(CalcState.waiting_surface_width)
async def surface_width(message: Message, state: FSMContext):
    try:
        width_cm = parse_float(message.text)
    except Exception:
        await message.answer("Введите корректную ширину в см.")
        return

    await state.update_data(current_width_cm=width_cm)
    await state.set_state(CalcState.waiting_surface_sides)
    await message.answer("Сколько сторон оклеивать?", reply_markup=sides_kb())


@dp.callback_query(CalcState.waiting_surface_sides, F.data.startswith("sides:"))
async def surface_sides(callback: CallbackQuery, state: FSMContext):
    sides = int(callback.data.split(":")[1])

    data = await state.get_data()
    name = data["current_name"]
    length_cm = data["current_length_cm"]
    width_cm = data["current_width_cm"]

    area_m2 = (length_cm / 100) * (width_cm / 100) * sides
    surfaces = data.get("surfaces", [])
    surfaces.append({
        "name": name, "length_cm": length_cm, "width_cm": width_cm, "sides": sides, "area": area_m2
    })

    await state.update_data(
        surfaces=surfaces, current_name=None, current_length_cm=None, current_width_cm=None
    )

    await callback.message.answer(
        f"✅ Добавлено: {name} — {fmt(area_m2)} м² ({'2 стороны' if sides == 2 else '1 сторона'})\n\n"
        f"{surfaces_summary(surfaces)}",
        reply_markup=surfaces_kb()
    )
    await state.set_state(CalcState.waiting_surface_name)
    await callback.answer()


@dp.callback_query(F.data == "surface:add")
async def add_more_surface(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CalcState.waiting_surface_name)
    await callback.message.answer("Введите название следующей поверхности:")
    await callback.answer()


@dp.callback_query(F.data == "surface:clear")
async def clear_surfaces(callback: CallbackQuery, state: FSMContext):
    await state.update_data(surfaces=[])
    await state.set_state(CalcState.waiting_surface_name)
    await callback.message.answer("Список очищен. Введите название поверхности:")
    await callback.answer()


@dp.callback_query(F.data == "surface:finish")
async def finish_surfaces(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    surfaces = data.get("surfaces", [])
    product_key = data.get("product_key", "all_products")

    if not surfaces:
        await callback.message.answer("Вы ещё не добавили поверхности.")
        await callback.answer()
        return

    total = surfaces_total(surfaces)
    counts = calc_counts_for_product(product_key, total)
    await state.update_data(last_area=total, last_counts=counts)

    text = surfaces_summary(surfaces) + "\n\n" + render_counts(total, counts)
    await callback.message.answer(text + "\n\nХотите рассчитать стоимость в рублях?", reply_markup=price_choice_kb())
    await state.set_state(CalcState.waiting_ask_price)
    await callback.answer()


@dp.callback_query(CalcState.waiting_ask_price, F.data == "price:no")
async def price_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Готово ✅\nНовый расчёт:", reply_markup=main_menu_kb())
    await state.clear()
    await callback.answer()


@dp.callback_query(CalcState.waiting_ask_price, F.data == "price:yes")
async def price_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    counts = data.get("last_counts", {})
    if not counts:
        await callback.message.answer("Сначала выполните расчёт количества.")
        await callback.answer()
        return

    if counts["type"] in ("single", "auto_pick"):
        await callback.message.answer("Введите цену за 1 упаковку/рулон в ₽ (например: 790)")
        await state.set_state(CalcState.waiting_price_single)
    else:
        await callback.message.answer("Введите цену за 1 рулон плёнки 60×3 м (₽):")
        await state.set_state(CalcState.waiting_price_all_film)

    await callback.answer()


@dp.message(CalcState.waiting_price_single)
async def handle_price_single(message: Message, state: FSMContext):
    try:
        price = parse_float(message.text)
    except Exception:
        await message.answer("Введите корректную цену, например: 850")
        return

    data = await state.get_data()
    counts = data["last_counts"]

    if counts["type"] == "single":
        qty = counts["count"]
        total_cost = qty * price
        text = f"💰 Стоимость:\n{qty} × {fmt(price)} ₽ = {money(total_cost)}"
    else:
        qty = counts["best"]["count"]
        label = counts["best"]["label"]
        total_cost = qty * price
        text = f"💰 Стоимость ({label}):\n{qty} × {fmt(price)} ₽ = {money(total_cost)}"

    await message.answer(text + "\n\nНовый расчёт 👇", reply_markup=main_menu_kb())
    await state.clear()


@dp.message(CalcState.waiting_price_all_film)
async def handle_price_all_film(message: Message, state: FSMContext):
    try:
        await state.update_data(price_film=parse_float(message.text))
    except Exception:
        await message.answer("Введите корректную цену.")
        return
    await state.set_state(CalcState.waiting_price_all_30x30)
    await message.answer("Введите цену за 1 упаковку панелей 30×30 (20 шт/уп), ₽:")


@dp.message(CalcState.waiting_price_all_30x30)
async def handle_price_all_3030(message: Message, state: FSMContext):
    try:
        await state.update_data(price_3030=parse_float(message.text))
    except Exception:
        await message.answer("Введите корректную цену.")
        return
    await state.set_state(CalcState.waiting_price_all_30x60_10)
    await message.answer("Введите цену за 1 упаковку панелей 30×60 (10 шт/уп), ₽:")


@dp.message(CalcState.waiting_price_all_30x60_10)
async def handle_price_all_3060_10(message: Message, state: FSMContext):
    try:
        await state.update_data(price_3060_10=parse_float(message.text))
    except Exception:
        await message.answer("Введите корректную цену.")
        return
    await state.set_state(CalcState.waiting_price_all_30x60_18)
    await message.answer("Введите цену за 1 упаковку панелей 30×60 (18 шт/уп), ₽:")


@dp.message(CalcState.waiting_price_all_30x60_18)
async def handle_price_all_3060_18(message: Message, state: FSMContext):
    try:
        price_3060_18 = parse_float(message.text)
    except Exception:
        await message.answer("Введите корректную цену.")
        return

    data = await state.get_data()
    counts = data["last_counts"]

    film_cost = counts["film_cnt"] * data["price_film"]
    p3030_cost = counts["p3030_cnt"] * data["price_3030"]
    p3060_10_cost = counts["p3060_10_cnt"] * data["price_3060_10"]
    p3060_18_cost = counts["p3060_18_cnt"] * price_3060_18

    total_if_10 = film_cost + p3030_cost + p3060_10_cost
    total_if_18 = film_cost + p3030_cost + p3060_18_cost

    await message.answer(
        "💰 Стоимость по всем товарам:\n\n"
        f"1) Плёнка: {money(film_cost)}\n"
        f"2) Панели 30×30: {money(p3030_cost)}\n"
        f"3) Панели 30×60 (10): {money(p3060_10_cost)}\n"
        f"4) Панели 30×60 (18): {money(p3060_18_cost)}\n\n"
        f"Итого с 30×60 (10): {money(total_if_10)}\n"
        f"Итого с 30×60 (18): {money(total_if_18)}\n\n"
        "Новый расчёт 👇",
        reply_markup=main_menu_kb()
    )
    await state.clear()
from flask import Flask
import threading

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

async def main():
    bot = Bot(BOT_TOKEN)

    threading.Thread(target=run_web).start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())





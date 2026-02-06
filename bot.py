import os
import math
import asyncio
import threading
from typing import Dict, Any, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from flask import Flask


# =========================
# ENV
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден. Добавь его в Environment Variables в Render.")


# =========================
# PRODUCTS
# =========================
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
    "laminate": {
        "title": "Ламинат 91.44×15.24 см (18 шт/уп)",
        "pack_area": 2.508,          # м²/уп
        "pack_name": "упаковок",
        "waste_percent": 0.10,       # 10%
        "waste_default_on": True,    # по умолчанию ВКЛ
    },
}


# =========================
# FSM STATES
# =========================
class CalcState(StatesGroup):
    choose_waste = State()          # только для ламината
    choose_input_mode = State()     # для остальных товаров

    waiting_total_area = State()

    waiting_surface_name = State()
    waiting_surface_length = State()
    waiting_surface_width = State()
    waiting_surface_sides = State()

    ask_openings = State()
    waiting_opening_type = State()
    waiting_opening_width = State()
    waiting_opening_height = State()

    waiting_ask_price = State()
    waiting_price_single = State()


dp = Dispatcher()


# =========================
# TEXT + KEYBOARDS
# =========================
def welcome_text() -> str:
    return (
        "✨ the_all4u — самоклеящиеся покрытия\n\n"
        "Не знаете, сколько материала нужно?\n"
        "Я рассчитаю всё за вас:\n\n"
        "✔ плёнка 60 см *3м\n"
        "✔ панели 30×30 см\n"
        "✔ панели 30×60 см\n"
        "✔ ламинат 91.44×15.24 см (18 шт/уп)\n"
        "✔ учёт окон/дверей (проёмов)\n"
        "✔ запас 10% для ламината (ВКЛ/ВЫКЛ)\n"
        "✔ расчёт стоимости\n\n"
        "Выберите вариант расчёта и получите точный результат 👌"
    )


def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="1) Плёнка 60×3 м", callback_data="calc:film_60x3")
    kb.button(text="2) Панели 30×30 (20 шт/уп)", callback_data="calc:panel_30x30_20")
    kb.button(text="3) Панели 30×60 (автоподбор)", callback_data="calc:panel_30x60_auto")
    kb.button(text="4) Ламинат 91.44×15.24 (18 шт/уп)", callback_data="calc:laminate")
    kb.adjust(1)
    return kb.as_markup()


def input_mode_kb(product_key: str):
    kb = InlineKeyboardBuilder()
    # Для ламината поверхности не нужны
    if product_key != "laminate":
        kb.button(text="Быстрый ввод общей площади (м²)", callback_data="mode:total")
        kb.button(text="Добавить поверхности (мебель/полки/стол)", callback_data="mode:surfaces")
    else:
        kb.button(text="Ввести площадь пола/стены (м²)", callback_data="mode:total")
    kb.button(text="⬅️ Назад к выбору товара", callback_data="back:products")
    kb.adjust(1)
    return kb.as_markup()


def surfaces_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить ещё поверхность", callback_data="surface:add")
    kb.button(text="✅ Завершить и перейти к проёмам", callback_data="surface:finish")
    kb.button(text="🧹 Очистить список", callback_data="surface:clear")
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
    kb.button(text="✅ Да, рассчитать стоимость", callback_data="price:yes")
    kb.button(text="❌ Нет, только количество", callback_data="price:no")
    kb.button(text="⬅️ Назад к выбору товара", callback_data="back:products")
    kb.adjust(1)
    return kb.as_markup()


def waste_toggle_kb(is_on: bool):
    kb = InlineKeyboardBuilder()
    status = "ВКЛ ✅" if is_on else "ВЫКЛ ❌"
    kb.button(text=f"Запас 10%: {status} (нажми, чтобы переключить)", callback_data="waste:toggle")
    kb.button(text="➡️ Далее", callback_data="waste:continue")
    kb.button(text="⬅️ Назад к выбору товара", callback_data="back:products")
    kb.adjust(1)
    return kb.as_markup()


def openings_yesno_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Нет, без проёмов", callback_data="openings:no")
    kb.button(text="Да, добавить окна/двери", callback_data="openings:yes")
    kb.adjust(1)
    return kb.as_markup()


def opening_mode_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🚪 Добавить дверь", callback_data="opening_type:door")
    kb.button(text="🪟 Добавить окно", callback_data="opening_type:window")
    kb.button(text="✅ Готово, рассчитать", callback_data="opening:finish")
    kb.button(text="🧹 Очистить проёмы", callback_data="opening:clear")
    kb.adjust(1)
    return kb.as_markup()


def opening_presets_kb(opening_type: str):
    kb = InlineKeyboardBuilder()

    if opening_type == "door":
        # (ширина, высота) в метрах
        presets = [
            ("🚪 70×200 см", "0.7", "2.0"),
            ("🚪 80×200 см", "0.8", "2.0"),
            ("🚪 90×200 см", "0.9", "2.0"),
            ("🚪 90×210 см", "0.9", "2.1"),
        ]
    else:
        presets = [
            ("🪟 120×120 см", "1.2", "1.2"),
            ("🪟 140×140 см", "1.4", "1.4"),
            ("🪟 150×150 см", "1.5", "1.5"),
            ("🪟 180×140 см", "1.8", "1.4"),
        ]

    for label, w, h in presets:
        kb.button(text=label, callback_data=f"opening_preset:{opening_type}:{w}:{h}")

    kb.button(text="⌨️ Ввести вручную", callback_data=f"opening_manual:{opening_type}")
    kb.button(text="⬅️ Назад к выбору типа", callback_data="opening:back_to_type")
    kb.button(text="✅ Готово, рассчитать", callback_data="opening:finish")
    kb.button(text="🧹 Очистить проёмы", callback_data="opening:clear")
    kb.adjust(1)
    return kb.as_markup()


# =========================
# HELPERS
# =========================
def fmt(n: float) -> str:
    return f"{n:.2f}".rstrip("0").rstrip(".")


def money(n: float) -> str:
    return f"{n:,.2f}".replace(",", " ") + " ₽"


def parse_float(text: str) -> float:
    v = float(text.strip().replace(",", "."))
    if v <= 0:
        raise ValueError
    return v


def parse_length_to_m(text: str) -> float:
    """
    Поддержка:
      - 1.2 / 0,8          -> метры
      - 120 см / 120cm     -> сантиметры
      - 120 (без единиц)   -> если >=10, считаем см; иначе м
    """
    t = text.strip().lower().replace(",", ".")
    t = t.replace(" ", "")
    is_cm = ("см" in t) or ("cm" in t)
    t = t.replace("см", "").replace("cm", "")
    val = float(t)
    if val <= 0:
        raise ValueError
    if is_cm:
        return val / 100.0
    return val / 100.0 if val >= 10 else val


def with_reserve(area: float, reserve: float) -> float:
    return area * (1 + reserve)


def packs_needed(area_with_reserve: float, pack_area: float) -> int:
    return math.ceil(area_with_reserve / pack_area)


def openings_total(openings: List[Dict[str, Any]]) -> float:
    return sum(o["area"] for o in openings)


def openings_summary(openings: List[Dict[str, Any]]) -> str:
    if not openings:
        return "Проёмы не добавлены."
    lines = ["Проёмы (окна/двери):"]
    for i, o in enumerate(openings, 1):
        icon = "🚪" if o.get("type") == "door" else "🪟"
        type_ru = "Дверь" if o.get("type") == "door" else "Окно"
        lines.append(f"{i}) {icon} {type_ru}: {fmt(o['w_m'])} × {fmt(o['h_m'])} м = {fmt(o['area'])} м²")
    lines.append(f"\nИтого проёмов: {fmt(openings_total(openings))} м²")
    return "\n".join(lines)


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


def calc_counts_for_product(product_key: str, area: float, reserve_percent: float) -> Dict[str, Any]:
    p = PRODUCTS[product_key]
    target = with_reserve(area, reserve_percent)

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
                "over": over,
            }
            variants.append(item)
            if best_over is None or over < best_over:
                best_over = over
                best = item
        return {
            "type": "auto_pick",
            "title": p["title"],
            "target_area": target,
            "reserve_percent": reserve_percent,
            "variants": variants,
            "best": best,
        }

    cnt = packs_needed(target, p["pack_area"])
    covered = cnt * p["pack_area"]
    return {
        "type": "single",
        "title": p["title"],
        "target_area": target,
        "reserve_percent": reserve_percent,
        "count": cnt,
        "pack_name": p["pack_name"],
        "covered": covered,
    }


def render_counts(base_area: float, openings_area: float, net_area: float, counts: Dict[str, Any]) -> str:
    rp = float(counts.get("reserve_percent", 0.10))
    reserve_line = (
        f"С запасом {int(rp * 100)}%: {fmt(counts['target_area'])} м²"
        if rp > 0 else
        f"Без запаса: {fmt(counts['target_area'])} м²"
    )

    lines = [
        f"📏 Площадь (введено): {fmt(base_area)} м²",
        f"🪟 Проёмы: − {fmt(openings_area)} м²" if openings_area > 0 else "🪟 Проёмы: не вычитаются",
        f"✅ Площадь к расчёту: {fmt(net_area)} м²",
        f"🧮 {reserve_line}",
        ""
    ]

    if counts["type"] == "single":
        lines += [
            f"🧱 {counts['title']}",
            f"Нужно: {counts['count']} {counts['pack_name']}",
            f"Покрытие: ~ {fmt(counts['covered'])} м²",
        ]
        return "\n".join(lines)

    lines.append(f"🧱 {counts['title']}")
    for v in counts["variants"]:
        lines.append(f"• {v['label']}: {v['count']} упаковок (покроет ~ {fmt(v['covered'])} м²)")
    lines += ["", f"✅ Рекомендация: {counts['best']['label']} — {counts['best']['count']} упаковок"]
    return "\n".join(lines)


# =========================
# HANDLERS
# =========================
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

    await state.update_data(
        product_key=key,
        reserve_percent=0.10,
        surfaces=[],
        openings=[],
        base_area=None,
        current_opening_w=None,
        current_opening_type=None
    )

    if key == "laminate":
        default_on = bool(PRODUCTS["laminate"].get("waste_default_on", True))
        await state.update_data(reserve_percent=(0.10 if default_on else 0.0))
        await state.set_state(CalcState.choose_waste)
        await callback.message.answer(
            f"Вы выбрали: {PRODUCTS[key]['title']}\n\nНужен запас 10%?",
            reply_markup=waste_toggle_kb(default_on),
        )
        await callback.answer()
        return

    await state.set_state(CalcState.choose_input_mode)
    await callback.message.answer(
        f"Вы выбрали: {PRODUCTS[key]['title']}\n\nКак хотите ввести площадь?",
        reply_markup=input_mode_kb(key)
    )
    await callback.answer()


# ---------- Ламинат: запас ----------
@dp.callback_query(CalcState.choose_waste, F.data == "waste:toggle")
async def waste_toggle(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    rp = float(data.get("reserve_percent", 0.10))
    new_rp = 0.0 if rp > 0 else 0.10
    await state.update_data(reserve_percent=new_rp)
    await callback.message.answer(
        f"Запас для ламината: {'ВКЛ ✅ (10%)' if new_rp > 0 else 'ВЫКЛ ❌ (0%)'}",
        reply_markup=waste_toggle_kb(new_rp > 0),
    )
    await callback.answer()


@dp.callback_query(CalcState.choose_waste, F.data == "waste:continue")
async def waste_continue(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CalcState.waiting_total_area)
    await callback.message.answer(
        "Введите площадь ПОЛА/СТЕНЫ в м² (например: 18.5)\n\n"
        "Далее при желании можно вычесть проёмы (окна/двери)."
    )
    await callback.answer()


# ---------- Режимы ввода площади ----------
@dp.callback_query(CalcState.choose_input_mode, F.data == "mode:total")
async def mode_total(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CalcState.waiting_total_area)
    await callback.message.answer(
        "Введите общую площадь в м² (например: 12.5)\n\n"
        "Если есть окна/двери — на следующем шаге можно их вычесть."
    )
    await callback.answer()


@dp.callback_query(CalcState.choose_input_mode, F.data == "mode:surfaces")
async def mode_surfaces(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("product_key") == "laminate":
        await callback.answer("Для ламината этот режим отключён.", show_alert=True)
        return

    await state.set_state(CalcState.waiting_surface_name)
    await callback.message.answer("Введите название поверхности (например: Стол, Полка 1, Дверца шкафа):")
    await callback.answer()


# ---------- Ввод общей площади ----------
@dp.message(CalcState.waiting_total_area)
async def process_total_area(message: Message, state: FSMContext):
    try:
        area = parse_float(message.text)
    except Exception:
        await message.answer("Введите корректное число, например: 9.8")
        return

    await state.update_data(base_area=area, openings=[])
    await state.set_state(CalcState.ask_openings)
    await message.answer(
        "Нужно вычесть проёмы (окна/двери) из этой площади?",
        reply_markup=openings_yesno_kb()
    )


# ---------- Поверхности ----------
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
        "name": name,
        "length_cm": length_cm,
        "width_cm": width_cm,
        "sides": sides,
        "area": area_m2,
    })

    await state.update_data(
        surfaces=surfaces,
        current_name=None,
        current_length_cm=None,
        current_width_cm=None,
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

    if not surfaces:
        await callback.message.answer("Вы ещё не добавили поверхности.")
        await callback.answer()
        return

    total = surfaces_total(surfaces)
    await state.update_data(base_area=total, openings=[])
    await state.set_state(CalcState.ask_openings)

    await callback.message.answer(
        surfaces_summary(surfaces) + "\n\nНужно вычесть проёмы (окна/двери)?",
        reply_markup=openings_yesno_kb()
    )
    await callback.answer()


# ---------- Проёмы ----------
@dp.callback_query(CalcState.ask_openings, F.data == "openings:no")
async def openings_no(callback: CallbackQuery, state: FSMContext):
    await state.update_data(openings=[])
    await finalize_calc(callback.message, state)
    await callback.answer()


@dp.callback_query(CalcState.ask_openings, F.data == "openings:yes")
async def openings_yes(callback: CallbackQuery, state: FSMContext):
    await state.update_data(openings=[])
    await state.set_state(CalcState.waiting_opening_type)
    await callback.message.answer(
        "Выберите тип проёма:",
        reply_markup=opening_mode_kb()
    )
    await callback.answer()


@dp.callback_query(CalcState.waiting_opening_type, F.data.startswith("opening_type:"))
async def opening_type_pick(callback: CallbackQuery, state: FSMContext):
    opening_type = callback.data.split(":")[1]  # door/window
    await state.update_data(current_opening_type=opening_type)
    title = "двери" if opening_type == "door" else "окна"
    await callback.message.answer(
        f"Выберите пресет для {title} или введите размер вручную:",
        reply_markup=opening_presets_kb(opening_type)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("opening_preset:"))
async def opening_preset_pick(callback: CallbackQuery, state: FSMContext):
    # opening_preset:{type}:{w}:{h}
    _, opening_type, w_str, h_str = callback.data.split(":")
    w_m = float(w_str)
    h_m = float(h_str)
    area = w_m * h_m

    data = await state.get_data()
    openings = data.get("openings", [])
    openings.append({
        "type": opening_type,
        "w_m": w_m,
        "h_m": h_m,
        "area": area
    })
    await state.update_data(openings=openings)

    icon = "🚪" if opening_type == "door" else "🪟"
    type_ru = "Дверь" if opening_type == "door" else "Окно"

    await callback.message.answer(
        f"✅ Добавлено: {icon} {type_ru} {fmt(w_m)}×{fmt(h_m)} м = {fmt(area)} м²\n\n"
        f"{openings_summary(openings)}",
        reply_markup=opening_mode_kb()
    )
    await state.set_state(CalcState.waiting_opening_type)
    await callback.answer()


@dp.callback_query(F.data.startswith("opening_manual:"))
async def opening_manual_pick(callback: CallbackQuery, state: FSMContext):
    opening_type = callback.data.split(":")[1]  # door/window
    await state.update_data(current_opening_type=opening_type)
    label = "двери" if opening_type == "door" else "окна"

    await state.set_state(CalcState.waiting_opening_width)
    await callback.message.answer(
        f"Введите ШИРИНУ {label}.\nМожно: 1.2 (м) или 120 см.\nЕсли просто число 120 — это будет 120 см."
    )
    await callback.answer()


@dp.callback_query(F.data == "opening:back_to_type")
async def opening_back_to_type(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CalcState.waiting_opening_type)
    await callback.message.answer(
        "Выберите тип проёма:",
        reply_markup=opening_mode_kb()
    )
    await callback.answer()


@dp.message(CalcState.waiting_opening_width)
async def opening_width(message: Message, state: FSMContext):
    try:
        w_m = parse_length_to_m(message.text)
    except Exception:
        await message.answer("Не понял ширину. Пример: 1.2 или 120 см")
        return

    await state.update_data(current_opening_w=w_m)
    await state.set_state(CalcState.waiting_opening_height)
    await message.answer("Теперь введите ВЫСОТУ (например: 2.1 или 210 см)")


@dp.message(CalcState.waiting_opening_height)
async def opening_height(message: Message, state: FSMContext):
    try:
        h_m = parse_length_to_m(message.text)
    except Exception:
        await message.answer("Не понял высоту. Пример: 2.1 или 210 см")
        return

    data = await state.get_data()
    w_m = float(data["current_opening_w"])
    opening_type = data.get("current_opening_type", "window")
    area = w_m * h_m

    openings = data.get("openings", [])
    openings.append({
        "type": opening_type,
        "w_m": w_m,
        "h_m": h_m,
        "area": area
    })

    await state.update_data(
        openings=openings,
        current_opening_w=None,
        current_opening_type=None
    )

    icon = "🚪" if opening_type == "door" else "🪟"
    type_ru = "Дверь" if opening_type == "door" else "Окно"

    await message.answer(
        f"✅ Добавлено: {icon} {type_ru} {fmt(w_m)}×{fmt(h_m)} м = {fmt(area)} м²\n\n"
        f"{openings_summary(openings)}",
        reply_markup=opening_mode_kb()
    )
    await state.set_state(CalcState.waiting_opening_type)


@dp.callback_query(F.data == "opening:clear")
async def opening_clear(callback: CallbackQuery, state: FSMContext):
    await state.update_data(openings=[], current_opening_type=None, current_opening_w=None)
    await state.set_state(CalcState.waiting_opening_type)
    await callback.message.answer(
        "Проёмы очищены. Выберите тип проёма:",
        reply_markup=opening_mode_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "opening:finish")
async def opening_finish(callback: CallbackQuery, state: FSMContext):
    await finalize_calc(callback.message, state)
    await callback.answer()


# ---------- Финал расчёта ----------
async def finalize_calc(message: Message, state: FSMContext):
    data = await state.get_data()

    product_key = data["product_key"]
    reserve_percent = float(data.get("reserve_percent", 0.10))

    base_area = float(data.get("base_area") or 0.0)
    openings = data.get("openings", [])
    openings_area = openings_total(openings)
    net_area = max(base_area - openings_area, 0.0)

    if net_area <= 0:
        await message.answer(
            "После вычета проёмов площадь стала 0 м².\n"
            "Проверьте данные и попробуйте ещё раз.",
            reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    counts = calc_counts_for_product(product_key, net_area, reserve_percent)

    await state.update_data(
        last_base_area=base_area,
        last_openings_area=openings_area,
        last_net_area=net_area,
        last_counts=counts,
    )

    await message.answer(
        render_counts(base_area, openings_area, net_area, counts)
        + "\n\nХотите рассчитать стоимость в рублях?",
        reply_markup=price_choice_kb()
    )
    await state.set_state(CalcState.waiting_ask_price)


# ---------- Стоимость ----------
@dp.callback_query(CalcState.waiting_ask_price, F.data == "price:no")
async def price_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Готово ✅\nНовый расчёт:", reply_markup=main_menu_kb())
    await state.clear()
    await callback.answer()


@dp.callback_query(CalcState.waiting_ask_price, F.data == "price:yes")
async def price_yes(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите цену за 1 упаковку/рулон (например: 790)")
    await state.set_state(CalcState.waiting_price_single)
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
        text = f"💰 Стоимость:\n{qty} × {fmt(price)} = {money(total_cost)}"
    else:
        qty = counts["best"]["count"]
        label = counts["best"]["label"]
        total_cost = qty * price
        text = f"💰 Стоимость ({label}):\n{qty} × {fmt(price)} = {money(total_cost)}"

    await message.answer(text + "\n\nНовый расчёт 👇", reply_markup=main_menu_kb())
    await state.clear()


# =========================
# FLASK (Render health check)
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


async def main():
    bot = Bot(BOT_TOKEN)
    threading.Thread(target=run_web, daemon=True).start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


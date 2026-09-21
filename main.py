"""
HabitFlow — минималистичный кроссплатформенный трекер полезных привычек.
Фреймворк: Flet (Python) — единая кодовая база для Web / Desktop / Mobile.

Архитектура (ООП, легко расширяется):
    Habit        — модель одной привычки (данные + бизнес-логика: streak, done_today)
    HabitStore   — слой хранения данных (асинхронное чтение/запись через page.client_storage,
                   что одинаково работает и в вебе, и на десктопе, и на мобильных —
                   в отличие от прямой записи в файл, которая на вебе недоступна)
    HabitApp     — слой UI (построение интерфейса, обработка событий, рендер списка)

Почему client_storage, а не файл/SQLite напрямую:
    page.client_storage — встроенный в Flet асинхронный key-value стор, который
    физически сохраняет данные в localStorage (веб) или в файле на диске
    (desktop/mobile) — то есть данные переживают перезапуск приложения на ЛЮБОЙ
    платформе без дополнительного кода. Именно это и требуется по ТЗ ("не пропадать
    при перезапуске"), и именно поэтому все операции с ним — async (чтобы не
    блокировать UI-поток при чтении/записи).

Запуск:
    pip install flet
    python main.py                 -> desktop-окно
    flet run --web main.py         -> в браузере
    flet run --android/--ios ...   -> см. README.md
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import List, Optional

import flet as ft

STORAGE_KEY = "habitflow.habits.v1"  # ключ, под которым хранится весь список привычек


# --------------------------------------------------------------------------------
# 1. МОДЕЛЬ ДАННЫХ
# --------------------------------------------------------------------------------

@dataclass
class Habit:
    """Одна привычка пользователя."""
    id: str
    title: str
    created_at: str                       # ISO-дата создания
    done_dates: List[str] = field(default_factory=list)  # список ISO-дат выполнения

    @staticmethod
    def create(title: str) -> "Habit":
        return Habit(
            id=str(uuid.uuid4()),
            title=title.strip(),
            created_at=date.today().isoformat(),
            done_dates=[],
        )

    def is_done_today(self) -> bool:
        return date.today().isoformat() in self.done_dates

    def toggle_today(self) -> None:
        """Отметить/снять отметку выполнения за сегодня."""
        today = date.today().isoformat()
        if today in self.done_dates:
            self.done_dates.remove(today)
        else:
            self.done_dates.append(today)

    def reset_today(self) -> None:
        today = date.today().isoformat()
        if today in self.done_dates:
            self.done_dates.remove(today)

    def current_streak(self) -> int:
        """Текущая серия дней подряд (включая сегодня, если отмечено)."""
        if not self.done_dates:
            return 0
        done = set(self.done_dates)
        streak = 0
        cursor = date.today()
        # если сегодня ещё не отмечено — серия считается от вчерашнего дня
        if cursor.isoformat() not in done:
            cursor -= timedelta(days=1)
        while cursor.isoformat() in done:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Habit":
        return Habit(
            id=data.get("id", str(uuid.uuid4())),
            title=data.get("title", ""),
            created_at=data.get("created_at", date.today().isoformat()),
            done_dates=list(data.get("done_dates", [])),
        )


# --------------------------------------------------------------------------------
# 2. СЛОЙ ХРАНЕНИЯ (асинхронный, не блокирует интерфейс)
# --------------------------------------------------------------------------------

class HabitStore:
    """Отвечает за загрузку/сохранение списка привычек через page.client_storage."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.habits: List[Habit] = []

    async def load(self) -> List[Habit]:
        raw: Optional[str] = await self.page.client_storage.get_async(STORAGE_KEY)
        if not raw:
            self.habits = []
            return self.habits
        try:
            items = json.loads(raw)
            self.habits = [Habit.from_dict(item) for item in items]
        except (json.JSONDecodeError, TypeError):
            # повреждённые данные — не роняем приложение, начинаем с чистого списка
            self.habits = []
        return self.habits

    async def save(self) -> None:
        payload = json.dumps([h.to_dict() for h in self.habits], ensure_ascii=False)
        await self.page.client_storage.set_async(STORAGE_KEY, payload)

    async def add(self, title: str) -> Habit:
        habit = Habit.create(title)
        self.habits.insert(0, habit)
        await self.save()
        return habit

    async def delete(self, habit_id: str) -> None:
        self.habits = [h for h in self.habits if h.id != habit_id]
        await self.save()

    async def clear_all(self) -> None:
        self.habits = []
        await self.save()

    async def reset_today_all(self) -> None:
        for h in self.habits:
            h.reset_today()
        await self.save()


# --------------------------------------------------------------------------------
# 3. UI / ПРИЛОЖЕНИЕ
# --------------------------------------------------------------------------------

# Цветовая палитра (тёмная тема, современный минимализм)
BG_COLOR = "#0F1115"
SURFACE_COLOR = "#1A1D23"
SURFACE_COLOR_HOVER = "#22262E"
ACCENT_COLOR = "#6C5CE7"
ACCENT_COLOR_SOFT = "#443B7A"
TEXT_PRIMARY = "#F2F2F5"
TEXT_SECONDARY = "#8A8F98"
DANGER_COLOR = "#E85D5D"
SUCCESS_COLOR = "#3DDC97"


class HabitApp:
    """Строит интерфейс и связывает его с HabitStore."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.store = HabitStore(page)

        self._setup_page()

        # --- элементы управления ---
        self.new_habit_field = ft.TextField(
            hint_text="Например: пить 2л воды",
            border_radius=12,
            filled=True,
            fill_color=SURFACE_COLOR,
            border_color="transparent",
            focused_border_color=ACCENT_COLOR,
            color=TEXT_PRIMARY,
            hint_style=ft.TextStyle(color=TEXT_SECONDARY),
            content_padding=16,
            expand=True,
            on_submit=self.on_add_click,
        )

        self.add_button = ft.IconButton(
            icon=ft.Icons.ADD_ROUNDED,
            icon_color=ft.Colors.WHITE,
            bgcolor=ACCENT_COLOR,
            icon_size=26,
            tooltip="Добавить привычку",
            on_click=self.on_add_click,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
        )

        self.habits_list = ft.ListView(
            expand=True,
            spacing=10,
            padding=ft.Padding(left=0, top=8, right=0, bottom=8),
        )

        self.empty_state = ft.Column(
            [
                ft.Icon(ft.Icons.SELF_IMPROVEMENT_ROUNDED, size=56, color=TEXT_SECONDARY),
                ft.Text("Пока нет ни одной привычки", color=TEXT_SECONDARY, size=15),
                ft.Text("Добавьте первую выше 👆", color=TEXT_SECONDARY, size=13),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=6,
            visible=False,
        )

        self.progress_text = ft.Text("", color=TEXT_SECONDARY, size=13)
        self.progress_bar = ft.ProgressBar(
            value=0, color=ACCENT_COLOR, bgcolor=SURFACE_COLOR, height=6, border_radius=6
        )

        self.reset_button = ft.TextButton(
            content=ft.Row(
                [ft.Icon(ft.Icons.REPLAY_ROUNDED, size=16, color=TEXT_SECONDARY),
                 ft.Text("Сбросить сегодня", color=TEXT_SECONDARY, size=13)],
                spacing=6, tight=True,
            ),
            on_click=self.on_reset_today,
        )

        self.clear_button = ft.TextButton(
            content=ft.Row(
                [ft.Icon(ft.Icons.DELETE_SWEEP_ROUNDED, size=16, color=DANGER_COLOR),
                 ft.Text("Удалить все", color=DANGER_COLOR, size=13)],
                spacing=6, tight=True,
            ),
            on_click=self.on_clear_all,
        )

        self.page.add(self._build_layout())
        self.page.run_task(self.initial_load)

    # ---------------------------- настройка страницы ----------------------------

    def _setup_page(self) -> None:
        self.page.title = "HabitFlow — трекер привычек"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = BG_COLOR
        self.page.padding = 0
        self.page.window.min_width = 360
        self.page.window.min_height = 560
        self.page.window.width = 420
        self.page.window.height = 760
        self.page.fonts = {}
        self.page.theme = ft.Theme(color_scheme_seed=ACCENT_COLOR)

    def _build_layout(self) -> ft.Control:
        """Адаптивный макет: контент центрируется и ограничивается по ширине
        на широких (desktop) экранах и растягивается на всю ширину на мобильных."""
        header = ft.Column(
            [
                ft.Text("HabitFlow", size=28, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                ft.Text("Маленькие привычки — большие результаты", size=13, color=TEXT_SECONDARY),
            ],
            spacing=2,
        )

        input_row = ft.Row(
            [self.new_habit_field, self.add_button],
            spacing=10,
        )

        progress_block = ft.Column(
            [self.progress_bar, self.progress_text],
            spacing=6,
        )

        footer = ft.Row(
            [self.reset_button, self.clear_button],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        body = ft.Column(
            [
                header,
                ft.Container(height=18),
                input_row,
                ft.Container(height=16),
                progress_block,
                ft.Container(height=10),
                ft.Stack([self.habits_list, self.empty_state], expand=True),
                ft.Divider(color=SURFACE_COLOR, height=1),
                footer,
            ],
            expand=True,
        )

        # ResponsiveRow даёт адаптивность: на узких экранах — 12/12 (вся ширина),
        # на широких — колонка уже и центрируется, как "карточка" приложения.
        responsive_wrapper = ft.ResponsiveRow(
            [
                ft.Container(col={"xs": 12, "sm": 12, "md": 8, "lg": 6, "xl": 5}, content=body, expand=True),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            expand=True,
        )

        return ft.Container(
            content=responsive_wrapper,
            padding=ft.Padding(left=20, right=20, top=28, bottom=16),
            expand=True,
            bgcolor=BG_COLOR,
        )

    # ---------------------------- загрузка данных ----------------------------

    async def initial_load(self) -> None:
        await self.store.load()
        self.render_list()

    # ---------------------------- рендер списка ----------------------------

    def render_list(self) -> None:
        self.habits_list.controls.clear()

        for habit in self.store.habits:
            self.habits_list.controls.append(self._build_habit_card(habit))

        self.empty_state.visible = len(self.store.habits) == 0
        self._update_progress()
        self.page.update()

    def _update_progress(self) -> None:
        total = len(self.store.habits)
        done = sum(1 for h in self.store.habits if h.is_done_today())
        if total == 0:
            self.progress_text.value = ""
            self.progress_bar.value = 0
        else:
            self.progress_text.value = f"Сегодня выполнено: {done} из {total}"
            self.progress_bar.value = done / total

    def _build_habit_card(self, habit: Habit) -> ft.Control:
        done = habit.is_done_today()
        streak = habit.current_streak()

        checkbox = ft.Container(
            content=ft.Icon(
                ft.Icons.CHECK_ROUNDED if done else ft.Icons.CIRCLE_OUTLINED,
                color=ft.Colors.WHITE if done else TEXT_SECONDARY,
                size=20,
            ),
            width=34,
            height=34,
            border_radius=17,
            bgcolor=SUCCESS_COLOR if done else "transparent",
            border=None if done else ft.Border(
                left=ft.BorderSide(2, TEXT_SECONDARY),
                top=ft.BorderSide(2, TEXT_SECONDARY),
                right=ft.BorderSide(2, TEXT_SECONDARY),
                bottom=ft.BorderSide(2, TEXT_SECONDARY),
            ),
            alignment=ft.Alignment(0, 0),
            on_click=lambda e, h=habit: self.on_toggle_habit(h),
            ink=True,
        )

        title_text = ft.Text(
            habit.title,
            size=15,
            color=TEXT_PRIMARY if not done else TEXT_SECONDARY,
            weight=ft.FontWeight.W_500,
            style=ft.TextStyle(
                decoration=ft.TextDecoration.LINE_THROUGH if done else None,
            ),
        )

        streak_badge = ft.Row(
            [
                ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT_ROUNDED, size=14,
                        color=ACCENT_COLOR if streak > 0 else TEXT_SECONDARY),
                ft.Text(f"{streak} дн." if streak > 0 else "нет серии", size=12, color=TEXT_SECONDARY),
            ],
            spacing=4,
            tight=True,
        )

        delete_btn = ft.IconButton(
            icon=ft.Icons.CLOSE_ROUNDED,
            icon_color=TEXT_SECONDARY,
            icon_size=18,
            tooltip="Удалить привычку",
            on_click=lambda e, h=habit: self.on_delete_habit(h),
        )

        return ft.Container(
            content=ft.Row(
                [
                    checkbox,
                    ft.Column([title_text, streak_badge], spacing=2, expand=True),
                    delete_btn,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE_COLOR,
            border_radius=14,
            padding=ft.Padding(left=14, right=14, top=10, bottom=10),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

    # ---------------------------- обработчики событий ----------------------------

    def on_add_click(self, e: ft.ControlEvent) -> None:
        title = self.new_habit_field.value.strip() if self.new_habit_field.value else ""
        if not title:
            self.new_habit_field.error_text = "Введите название привычки"
            self.page.update()
            return
        self.new_habit_field.error_text = None
        self.new_habit_field.value = ""
        self.page.run_task(self._add_habit_async, title)

    async def _add_habit_async(self, title: str) -> None:
        await self.store.add(title)
        self.render_list()

    def on_toggle_habit(self, habit: Habit) -> None:
        habit.toggle_today()
        self.page.run_task(self._save_and_render)

    def on_delete_habit(self, habit: Habit) -> None:
        self.page.run_task(self._delete_habit_async, habit.id)

    async def _delete_habit_async(self, habit_id: str) -> None:
        await self.store.delete(habit_id)
        self.render_list()

    def on_reset_today(self, e: ft.ControlEvent) -> None:
        self.page.run_task(self._reset_today_async)

    async def _reset_today_async(self) -> None:
        await self.store.reset_today_all()
        self.render_list()

    def on_clear_all(self, e: ft.ControlEvent) -> None:
        def confirm_yes(ev):
            self.page.close(dialog)
            self.page.run_task(self._clear_all_async)

        def confirm_no(ev):
            self.page.close(dialog)

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=SURFACE_COLOR,
            title=ft.Text("Удалить все привычки?", color=TEXT_PRIMARY),
            content=ft.Text("Это действие нельзя отменить.", color=TEXT_SECONDARY),
            actions=[
                ft.TextButton("Отмена", on_click=confirm_no),
                ft.TextButton("Удалить", style=ft.ButtonStyle(color=DANGER_COLOR), on_click=confirm_yes),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dialog)

    async def _clear_all_async(self) -> None:
        await self.store.clear_all()
        self.render_list()


# --------------------------------------------------------------------------------
# ТОЧКА ВХОДА
# --------------------------------------------------------------------------------

def main(page: ft.Page) -> None:
    HabitApp(page)


if __name__ == "__main__":
    ft.run(main)

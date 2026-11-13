"""
gui.py — Компактный графический интерфейс и терминальный ввод для аудита рейсов Advantum.

Особенности:
- Чистый, минималистичный дизайн без лишней информации.
- Корректная работа Ctrl+V и Ctrl+A при ЛЮБОЙ раскладке клавиатуры (RU / EN).
- Кнопки управления жестко зафиксированы внизу окна (не обрезаются при любом масштабе экрана).
- Быстрый запуск по Ctrl+Enter или кнопке [Запустить аудит ▶].
- Поддержка терминального ввода через функцию prompt_trips_cli().
"""

import os
import re
import sys
from datetime import datetime, timedelta
from typing import List, Optional


def parse_trips_input(raw_text: str) -> List[str]:
    """Извлекает список уникальных номеров рейсов из любого текста."""
    if not raw_text:
        return []
    tokens = re.split(r"[\s,;\n\r\t]+", raw_text.strip())
    trips = []
    seen = set()
    for t in tokens:
        cleaned = re.sub(r"[^\w]", "", t).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            trips.append(cleaned)
    return trips


def parse_date_str(val: str, default: datetime) -> datetime:
    """Парсит строку даты ДД.ММ.ГГГГ или возвращает значение по умолчанию."""
    val = (val or "").strip()
    if not val:
        return default
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            pass
    return default


def prompt_trips_cli(default_days: int = 7) -> Optional[dict]:
    """Терминальный ввод номеров рейсов без открытия окна."""
    print("\n" + "=" * 64)
    print("       ВВОД НОМЕРОВ РЕЙСОВ ДЛЯ АУДИТА В ТЕРМИНАЛЕ")
    print("=" * 64)
    try:
        raw_trips = input(" Номера рейсов (через пробел или запятую): ").strip()
        trips = parse_trips_input(raw_trips)
        if not trips:
            print(" [Отмена] Рейсы не указаны.")
            return None

        return {
            "trips": trips,
            "dry_run": True,
            "no_recalc": True,
            "radius": None,
        }
    except (KeyboardInterrupt, EOFError):
        print("\n [Отмена]")
        return None


def show_batch_input_dialog(
    default_trips: Optional[List[str]] = None,
    default_date_from: Optional[datetime] = None,
    default_date_to: Optional[datetime] = None,
    default_radius: Optional[int] = None,
) -> Optional[dict]:
    """
    Открывает компактное графическое окно (Tkinter) для ввода списка рейсов.
    Кнопки гарантированно видны внизу экрана, а Ctrl+V работает на любой раскладке.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        return prompt_trips_cli()

    initial_trips_str = "\n".join(default_trips) if default_trips else ""

    result = {}
    root = tk.Tk()
    root.title("Аудит рейсов Advantum")
    root.geometry("460x240")
    root.minsize(400, 210)

    # Центрирование окна
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(50, (sw - 460) // 2)
    y = max(50, (sh - 240) // 2)
    root.geometry(f"460x240+{x}+{y}")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    main_frame = ttk.Frame(root, padding="12 12 12 12")
    main_frame.pack(fill=tk.BOTH, expand=True)

    # 1. ПАНЕЛЬ КНОПОК УПАКОВЫВАЕТСЯ ПЕРВОЙ В САМЫЙ НИЗ (side=BOTTOM),
    # благодаря чему она НИКОГДА не будет обрезана или вытолкнута за экран!
    btn_frame = ttk.Frame(main_frame)
    btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

    def on_submit():
        raw_trips = trips_text.get("1.0", tk.END)
        parsed = parse_trips_input(raw_trips)
        if not parsed:
            messagebox.showwarning(
                "Требуется ввод",
                "Пожалуйста, введите хотя бы один номер рейса!",
                parent=root,
            )
            return

        result["trips"] = parsed
        result["dry_run"] = True
        result["no_recalc"] = True
        result["radius"] = None
        root.destroy()

    def on_cancel():
        root.destroy()

    btn_cancel = ttk.Button(btn_frame, text="Отмена", command=on_cancel, width=12)
    btn_cancel.pack(side=tk.RIGHT, padx=(8, 0))

    btn_run = ttk.Button(
        btn_frame,
        text="Запустить аудит  ▶",
        command=on_submit,
        width=22,
    )
    btn_run.pack(side=tk.RIGHT)

    # 2. Поле ввода номеров рейсов
    lbl_trips = ttk.Label(
        main_frame,
        text="Номера рейсов (через пробел, запятую или с новой строки):",
        font=("Segoe UI" if sys.platform == "win32" else "Helvetica", 10, "bold"),
    )
    lbl_trips.pack(anchor="w", pady=(0, 4))

    trips_text = tk.Text(
        main_frame,
        height=5,
        font=("Consolas" if sys.platform == "win32" else "Courier", 11),
        wrap="word",
        relief="solid",
        borderwidth=1,
    )
    trips_text.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

    # 3. НАДЕЖНАЯ ОБРАБОТКА Ctrl+V И ГОРЯЧИХ КЛАВИШ НА ЛЮБОЙ РАСКЛАДКЕ
    def paste_clipboard():
        try:
            content = root.clipboard_get()
            try:
                trips_text.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError:
                pass
            trips_text.insert(tk.INSERT, content)
        except Exception:
            pass

    def on_key_event(event):
        # На Windows при нажатом Ctrl флаг event.state & 0x0004 равен True.
        # Физическая клавиша 'V' на клавиатуре имеет keycode 86 независимо от языка (RU/EN)!
        is_ctrl = bool(event.state & 0x0004) or bool(event.state & 0x0008)

        # Ctrl+V (Windows VK_V = 86, Mac = 9)
        if is_ctrl and (event.keycode in (86, 9) or event.keysym.lower() in ("v", "cyrillic_em", "m")):
            paste_clipboard()
            return "break"

        # Ctrl+A (Windows VK_A = 65, Mac = 0)
        if is_ctrl and (event.keycode in (65, 0) or event.keysym.lower() in ("a", "cyrillic_ef", "f")):
            trips_text.tag_add(tk.SEL, "1.0", tk.END)
            trips_text.mark_set(tk.INSERT, "1.0")
            trips_text.see(tk.INSERT)
            return "break"

        # Ctrl+C (Windows VK_C = 67, Mac = 8)
        if is_ctrl and (event.keycode in (67, 8) or event.keysym.lower() in ("c", "cyrillic_es", "s")):
            try:
                sel = trips_text.get(tk.SEL_FIRST, tk.SEL_LAST)
                root.clipboard_clear()
                root.clipboard_append(sel)
            except Exception:
                pass
            return "break"

        # Ctrl+Enter -> Быстрый запуск!
        if is_ctrl and event.keysym in ("Return", "KP_Enter"):
            on_submit()
            return "break"

        return None

    trips_text.bind("<KeyPress>", on_key_event)
    root.bind("<Control-Return>", lambda e: on_submit())
    root.bind("<Escape>", lambda e: on_cancel())

    # Контекстное меню по правому клику мыши
    ctx_menu = tk.Menu(trips_text, tearoff=0)
    ctx_menu.add_command(label="Вставить (Ctrl+V)", command=paste_clipboard)
    ctx_menu.add_command(label="Копировать (Ctrl+C)", command=lambda: trips_text.event_generate("<<Copy>>"))
    ctx_menu.add_command(label="Вырезать (Ctrl+X)", command=lambda: trips_text.event_generate("<<Cut>>"))
    ctx_menu.add_separator()
    ctx_menu.add_command(label="Очистить", command=lambda: trips_text.delete("1.0", tk.END))

    def show_popup(event):
        try:
            ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            ctx_menu.grab_release()

    trips_text.bind("<Button-3>", show_popup)

    if initial_trips_str:
        trips_text.insert("1.0", initial_trips_str)
    trips_text.focus_set()

    root.mainloop()
    return result if result else None

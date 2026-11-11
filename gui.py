"""
gui.py — Графическое окно ввода параметров для пакетной обработки рейсов.

Позволяет ввести:
- Один или несколько номеров рейсов (через запятую, пробел или построчно из Excel).
- Диапазон дат (Дата с ... по ...) для фильтра рейсов в Advantum.
- Радиус зоны в 1С (опционально).
- Флаги: только аудит (dry-run) и запрет пересчета телематики (no-recalc).
"""

import re
import sys
from datetime import datetime, timedelta
from typing import List, Optional, Tuple


def parse_trips_input(raw_text: str) -> List[str]:
    """
    Извлекает список уникальных номеров рейсов из любого текста:
    поддерживает разделение запятыми, пробелами, точкой с запятой и переносами строк.
    """
    if not raw_text:
        return []
    # Находим все последовательности цифр (длиной от 5 цифр для номеров рейсов)
    # или токены без пробелов/знаков препинания
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


def show_batch_input_dialog(
    default_trips: Optional[List[str]] = None,
    default_date_from: Optional[datetime] = None,
    default_date_to: Optional[datetime] = None,
    default_radius: Optional[int] = None,
) -> Optional[dict]:
    """
    Открывает графическое окно (Tkinter) для ввода списка рейсов и параметров.
    Возвращает dict с параметрами или None, если пользователь закрыл окно/нажал Отмена.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("[GUI] Tkinter недоступен в текущем окружении, используем консольный ввод.")
        return None

    now = datetime.now()
    d_to = default_date_to or now
    d_from = default_date_from or (d_to - timedelta(days=10))

    initial_trips_str = "\n".join(default_trips) if default_trips else ""

    result = {}

    root = tk.Tk()
    root.title("Аудит и диагностика причин неотбитых точек (Advantum <-> 1С)")
    root.geometry("560x530")
    root.minsize(480, 460)

    # Центрирование окна
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(50, (sw - 560) // 2)
    y = max(50, (sh - 530) // 2)
    root.geometry(f"560x530+{x}+{y}")

    # Стили
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    main_frame = ttk.Frame(root, padding="15 15 15 15")
    main_frame.pack(fill=tk.BOTH, expand=True)

    # 1. Заголовок
    header_lbl = ttk.Label(
        main_frame,
        text="Диагностика и аудит неотбитых точек рейсов",
        font=("Segoe UI" if sys.platform == "win32" else "Helvetica", 13, "bold"),
    )
    header_lbl.pack(anchor="w", pady=(0, 4))

    desc_lbl = ttk.Label(
        main_frame,
        text="Скрипт проведет детальный аудит рейсов по GPS-треку водителя и геоданным:\n"
             "• Определит, был ли водитель на адресе (по GPS-треку автомобиля)\n"
             "• Выявит опоздания (нарушение планового временного окна доставки)\n"
             "• Выявит ошибки координат ЕИС и недостаточный радиус зоны (парковки/шлагбаумы)\n"
             "• Сформирует подробный отчет с точной причиной по каждой точке.",
        font=("Segoe UI" if sys.platform == "win32" else "Helvetica", 9),
        foreground="#444444",
    )
    desc_lbl.pack(anchor="w", pady=(0, 10))

    # 2. Поле ввода номеров рейсов
    trips_frame = ttk.LabelFrame(main_frame, text=" Номера рейсов ", padding="8 8 8 8")
    trips_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

    trips_header = ttk.Frame(trips_frame)
    trips_header.pack(fill=tk.X, pady=(0, 4))

    trips_hint = ttk.Label(
        trips_header,
        text="Введите номера рейсов (через запятую, пробел или с новой строки):",
        font=("Segoe UI" if sys.platform == "win32" else "Helvetica", 9),
    )
    trips_hint.pack(side=tk.LEFT, anchor="w")

    def handle_paste(event=None):
        try:
            clipboard_content = root.clipboard_get()
            try:
                trips_text.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError:
                pass
            trips_text.insert(tk.INSERT, clipboard_content)
        except Exception:
            pass
        return "break"

    def handle_select_all(event=None):
        trips_text.tag_add(tk.SEL, "1.0", tk.END)
        trips_text.mark_set(tk.INSERT, "1.0")
        trips_text.see(tk.INSERT)
        return "break"

    btn_paste = ttk.Button(
        trips_header,
        text="📋 Вставить из буфера",
        command=handle_paste,
        width=20,
    )
    btn_paste.pack(side=tk.RIGHT)

    trips_text = tk.Text(
        trips_frame,
        height=5,
        font=("Consolas" if sys.platform == "win32" else "Courier", 11),
        wrap="word",
        relief="solid",
        borderwidth=1,
    )
    trips_text.pack(fill=tk.BOTH, expand=True)

    # Привязки горячих клавиш (включая русскую раскладку клавиатуры на Windows!)
    trips_text.bind("<Control-v>", handle_paste)
    trips_text.bind("<Control-V>", handle_paste)
    trips_text.bind("<Control-KeyPress-m>", handle_paste)
    trips_text.bind("<Control-KeyPress-M>", handle_paste)
    trips_text.bind("<Control-KeyPress-Cyrillic_em>", handle_paste)
    trips_text.bind("<Control-KeyPress-Cyrillic_EM>", handle_paste)
    trips_text.bind("<Shift-Insert>", handle_paste)
    trips_text.bind("<<Paste>>", handle_paste)

    trips_text.bind("<Control-a>", handle_select_all)
    trips_text.bind("<Control-A>", handle_select_all)
    trips_text.bind("<Control-KeyPress-f>", handle_select_all)
    trips_text.bind("<Control-KeyPress-F>", handle_select_all)
    trips_text.bind("<Control-KeyPress-Cyrillic_ef>", handle_select_all)
    trips_text.bind("<Control-KeyPress-Cyrillic_EF>", handle_select_all)

    # Контекстное меню по правому клику мыши
    menu = tk.Menu(trips_text, tearoff=0)
    menu.add_command(label="Вставить", command=handle_paste)
    menu.add_command(label="Копировать", command=lambda: trips_text.event_generate("<<Copy>>"))
    menu.add_command(label="Вырезать", command=lambda: trips_text.event_generate("<<Cut>>"))
    menu.add_separator()
    menu.add_command(label="Выделить всё", command=handle_select_all)
    menu.add_command(label="Очистить", command=lambda: trips_text.delete("1.0", tk.END))

    def show_context_menu(event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    trips_text.bind("<Button-3>", show_context_menu)
    if sys.platform == "darwin":
        trips_text.bind("<Button-2>", show_context_menu)

    if initial_trips_str:
        trips_text.insert("1.0", initial_trips_str)
    trips_text.focus_set()

    # 3. Период фильтрации в Advantum
    filter_frame = ttk.LabelFrame(main_frame, text=" Период рейсов в Advantum (ДД.ММ.ГГГГ) ", padding="8 8 8 8")
    filter_frame.pack(fill=tk.X, pady=(0, 10))

    dates_inner = ttk.Frame(filter_frame)
    dates_inner.pack(fill=tk.X)

    ttk.Label(dates_inner, text="Дата с:").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=2)
    entry_from = ttk.Entry(dates_inner, width=13, font=("Segoe UI" if sys.platform == "win32" else "Helvetica", 10))
    entry_from.insert(0, d_from.strftime("%d.%m.%Y"))
    entry_from.grid(row=0, column=1, sticky="w", padx=(0, 16), pady=2)

    ttk.Label(dates_inner, text="Дата по:").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=2)
    entry_to = ttk.Entry(dates_inner, width=13, font=("Segoe UI" if sys.platform == "win32" else "Helvetica", 10))
    entry_to.insert(0, d_to.strftime("%d.%m.%Y"))
    entry_to.grid(row=0, column=3, sticky="w", padx=(0, 8), pady=2)

    # 4. Режим работы
    opts_frame = ttk.LabelFrame(main_frame, text=" Режим выполнения ", padding="8 8 8 8")
    opts_frame.pack(fill=tk.X, pady=(0, 12))

    dry_run_var = tk.BooleanVar(value=True)
    no_recalc_var = tk.BooleanVar(value=False)

    chk_dry = ttk.Checkbutton(
        opts_frame,
        text="Только аудит и отчет (Рекомендуется — не вносить изменения в 1С)",
        variable=dry_run_var,
    )
    chk_dry.pack(anchor="w", pady=(2, 2))

    chk_recalc = ttk.Checkbutton(
        opts_frame,
        text="Не пересчитывать телематику в Advantum (--no-recalc)",
        variable=no_recalc_var,
    )
    chk_recalc.pack(anchor="w", pady=(0, 2))

    radius_row = ttk.Frame(opts_frame)
    radius_row.pack(fill=tk.X, pady=(4, 2))
    ttk.Label(radius_row, text="Тестовый радиус зоны (м, опционально):").pack(side=tk.LEFT, padx=(0, 8))
    entry_radius = ttk.Entry(radius_row, width=8, font=("Segoe UI" if sys.platform == "win32" else "Helvetica", 10))
    if default_radius:
        entry_radius.insert(0, str(default_radius))
    entry_radius.pack(side=tk.LEFT)

    # 5. Кнопки управления
    btn_frame = ttk.Frame(main_frame)
    btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

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

        str_from = entry_from.get().strip()
        str_to = entry_to.get().strip()

        dt_from = parse_date_str(str_from, d_from)
        dt_to = parse_date_str(str_to, d_to)
        if dt_from > dt_to:
            dt_from, dt_to = dt_to, dt_from

        r_val = entry_radius.get().strip()
        radius_num = None
        if r_val.isdigit():
            radius_num = int(r_val)

        result["trips"] = parsed
        result["date_from"] = dt_from
        result["date_to"] = dt_to
        result["radius"] = radius_num
        result["dry_run"] = dry_run_var.get()
        result["no_recalc"] = no_recalc_var.get()

        root.destroy()

    def on_cancel():
        root.destroy()

    root.bind("<Escape>", lambda e: on_cancel())

    btn_cancel = ttk.Button(btn_frame, text="Отмена", command=on_cancel, width=12)
    btn_cancel.pack(side=tk.RIGHT, padx=(8, 0))

    btn_run = ttk.Button(
        btn_frame,
        text="Запустить обработку  ▶",
        command=on_submit,
        width=24,
    )
    btn_run.pack(side=tk.RIGHT)

    root.mainloop()

    return result if result else None

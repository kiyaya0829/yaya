"""Yaya Journal desktop UI (Python standard library only)."""
from datetime import date
from decimal import Decimal
import argparse
from pathlib import Path
import sqlite3
import tempfile
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from journal import Journal, VERSION
from quotes import QuoteBook
from key_store import load_key, save_key


class App:
    def __init__(self, root, journal):
        self.root, self.journal = root, journal
        self.selected = None
        self.rows = {}
        self.quote_book = QuoteBook(journal)
        self.quote_queue = queue.Queue()
        self.quote_running = False
        self.quote_cancel = threading.Event()
        self.quote_window = None
        root.title(f"Yaya 交易日记 · {VERSION}")
        root.geometry("1120x760")
        root.minsize(900, 650)
        root.configure(bg="#f4f6fa")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6fa")
        style.configure("TLabel", background="#f4f6fa", foreground="#203047", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"))
        style.configure("Muted.TLabel", foreground="#64748b")
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(12, 7))
        style.configure("Treeview", font=("Microsoft YaHei UI", 10), rowheight=32, background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), padding=8)
        style.map("Treeview", background=[("selected", "#dce8fa")], foreground=[("selected", "#172b4d")])
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Yaya 交易日记", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="记下每次决定，也留一点空间给下一次成长。", style="Muted.TLabel").pack(anchor="w", pady=(4, 18))
        quote_bar = ttk.Frame(outer)
        quote_bar.pack(fill='x', pady=(0, 10))
        ttk.Button(quote_bar, text='美股持仓 / 收盘行情', command=self.show_positions).pack(side='left')
        ttk.Button(quote_bar, text='更新收盘价', command=self.update_quotes).pack(side='left', padx=6)
        ttk.Button(quote_bar, text='行情设置', command=self.quote_settings).pack(side='right')
        self.quote_status = tk.StringVar(value='打开时自动检查收盘行情；交易记录始终保存在本机。')
        ttk.Label(outer, textvariable=self.quote_status, wraplength=1020, style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Label(toolbar, text="搜索代码 / 笔记").pack(side="left", padx=(0, 8))
        self.query = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.query, width=28).pack(side="left")
        self.query.trace_add("write", lambda *_: self.refresh())
        ttk.Button(toolbar, text="备份记录", command=self.backup).pack(side="right")
        table = ttk.Frame(outer)
        table.pack(fill="both", expand=True)
        columns = ("date", "market", "symbol", "side", "currency", "price", "quantity", "note")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for col, label, width in zip(columns, ("日期", "市场", "股票代码", "方向", "币种", "成交价", "数量", "笔记"), (105, 65, 100, 60, 60, 100, 100, 220)):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=55, stretch=col == "note")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.select)
        self.status = tk.StringVar()
        ttk.Label(outer, textvariable=self.status, style="Muted.TLabel").pack(anchor="w", pady=(8, 14))
        self.editor_title = tk.StringVar(value="新增交易")
        ttk.Label(outer, textvariable=self.editor_title, font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        form = ttk.Frame(outer)
        form.pack(fill="x", pady=10)
        self.fields = {}
        specs = [("market", "市场", "US", ['US', '其他', '待确认']), ("symbol", "股票代码", "", None), ("side", "方向", "买入", ["买入", "卖出"]),
                 ("currency", "币种", "USD", ["USD", "HKD", "CNY", "SGD", "EUR", "JPY", "GBP"]),
                 ("price", "成交价", "", None), ("quantity", "数量", "", None),
                 ("traded_on", "日期 YYYY-MM-DD", date.today().isoformat(), None)]
        for i, (key, label, value, choices) in enumerate(specs):
            form.columnconfigure(i, weight=1)
            ttk.Label(form, text=label).grid(row=0, column=i, sticky="w", padx=(0, 10))
            variable = self.fields[key] = tk.StringVar(value=value)
            if choices:
                widget = ttk.Combobox(form, textvariable=variable, values=choices, state="readonly", width=9)
            else:
                widget = ttk.Entry(form, textvariable=variable, width=14)
            widget.grid(row=1, column=i, sticky="ew", padx=(0, 10), pady=(5, 0))
        ttk.Label(outer, text="交易理由 / 复盘笔记").pack(anchor="w")
        self.note = tk.Text(outer, height=4, wrap="word", font=("Microsoft YaHei UI", 10), relief="solid", borderwidth=1, padx=10, pady=8, undo=True)
        self.note.pack(fill="x", pady=(5, 12))
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="保存记录", command=self.save).pack(side="left")
        ttk.Button(buttons, text="新建 / 清空", command=self.new).pack(side="left", padx=8)
        self.delete_button = ttk.Button(buttons, text="删除所选", command=self.delete, state="disabled")
        self.delete_button.pack(side="right")
        ttk.Label(outer, text="交易本机保存 · 清仓停止行情更新，保留历史记录 · 不连接券商", style="Muted.TLabel").pack(anchor="w", pady=(14, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self.root.after(500, self.update_quotes)

    def values(self):
        return {**{key: var.get().strip() for key, var in self.fields.items()}, "note": self.note.get("1.0", "end-1c")}

    def refresh(self):
        rows = self.journal.all(self.query.get())
        self.tree.delete(*self.tree.get_children())
        self.rows = {str(row['id']): row for row in rows}
        for iid, row in self.rows.items():
            self.tree.insert("", "end", iid=iid, values=tuple(row[key] if key != "note" else row[key].replace("\n", " · ") for key in ("traded_on", "market", "symbol", "side", "currency", "price", "quantity", "note")))
        self.status.set(f"显示 {len(rows)} 条记录 · 点击记录可编辑" if rows else "还没有匹配的记录。在下方写下第一笔交易吧。")

    def select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        row = self.rows[selection[0]]
        self.selected = row['id']
        for key, variable in self.fields.items():
            variable.set(row[key])
        self.note.delete("1.0", "end")
        self.note.insert("1.0", row['note'])
        self.editor_title.set(f"编辑交易 · {row['symbol']}")
        self.delete_button.configure(state="normal")

    def new(self):
        self.selected = None
        self.tree.selection_remove(*self.tree.selection())
        for key, variable in self.fields.items():
            variable.set({"market": "US", "side": "买入", "currency": "USD", "traded_on": date.today().isoformat()}.get(key, ""))
        self.note.delete("1.0", "end")
        self.editor_title.set("新增交易")
        self.delete_button.configure(state="disabled")

    def save(self):
        try:
            self.journal.save(trade_id=self.selected, **self.values())
        except (ValueError, sqlite3.Error, OSError) as exc:
            messagebox.showerror("未能保存", str(exc), parent=self.root)
            return
        self.new()
        self.refresh()
        self.status.set(self.status.get() + " · 已保存")
        self.render_positions()
        self.quote_status.set('记录已保存；行情按当前持仓展示。可点击更新收盘价。')

    def delete(self):
        if self.selected is None:
            return
        if messagebox.askyesno("删除记录", "确定删除这条交易记录？此操作无法撤销。", parent=self.root):
            try:
                self.journal.delete(self.selected)
            except (sqlite3.Error, ValueError) as exc:
                messagebox.showerror("未能删除", str(exc), parent=self.root)
                return
            self.new()
            self.refresh()
            self.render_positions()

    def quote_settings(self):
        window = tk.Toplevel(self.root)
        window.title('行情设置')
        window.geometry('620x250')
        box = ttk.Frame(window, padding=20)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text='Alpha Vantage API Key（个人账号）').pack(anchor='w')
        value = tk.StringVar()
        entry = ttk.Entry(box, textvariable=value, show='*', width=60)
        entry.pack(fill='x', pady=12)
        ttk.Label(box, text='填写并保存后开始自动更新。留空保存可移除已存密钥。\n密钥由 Windows 保护，独立存放，不写入日记备份。\n已有密钥不回显；取消不会修改。', wraplength=570).pack(anchor='w')
        def commit():
            try:
                save_key(self.journal.path.parent, value.get())
            except OSError as exc:
                messagebox.showerror('无法保存设置', str(exc), parent=window)
                return
            window.destroy()
            self.update_quotes()
        controls = ttk.Frame(box)
        controls.pack(fill='x', pady=10)
        ttk.Button(controls, text='保存', command=commit).pack(side='left')
        ttk.Button(controls, text='取消', command=window.destroy).pack(side='left', padx=8)
        import webbrowser
        ttk.Button(controls, text='申请免费 API Key', command=lambda: webbrowser.open('https://www.alphavantage.co/support/#api-key')).pack(side='right')

    def show_positions(self):
        if self.quote_window is not None and self.quote_window.winfo_exists():
            self.quote_window.lift()
            self.render_positions()
            return
        self.quote_window = tk.Toplevel(self.root)
        self.quote_window.title('Yaya · 美股持仓收盘行情')
        self.quote_window.geometry('770x440')
        box = ttk.Frame(self.quote_window, padding=20)
        box.pack(fill='both', expand=True)
        self.snapshot_label = tk.StringVar()
        ttk.Label(box, textvariable=self.snapshot_label, wraplength=720).pack(anchor='w', pady=(0, 12))
        self.positions_tree = ttk.Treeview(box, columns=('symbol','shares','close'), show='headings')
        for column, title in zip(('symbol','shares','close'), ('美股代码','当前持仓数量','收盘价 USD')):
            self.positions_tree.heading(column, text=title)
            self.positions_tree.column(column, width=200)
        self.positions_tree.pack(fill='both', expand=True)
        ttk.Label(box, textvariable=self.quote_status, wraplength=720).pack(anchor='w', pady=10)
        ttk.Label(box, text='仅展示已确认 US 的普通多头持仓；未复权价格，不计算总资产或盈亏。', wraplength=720).pack(anchor='w')
        self.render_positions()

    def render_positions(self):
        if self.quote_window is None or not self.quote_window.winfo_exists():
            return
        day, rows = self.quote_book.snapshot()
        self.positions_tree.delete(*self.positions_tree.get_children())
        for row in rows:
            self.positions_tree.insert('', 'end', values=row)
        self.snapshot_label.set(f'统一收盘日期：{day}（美国交易日） · Alpha Vantage' if day else ('行情准备中：所有持仓齐全后统一显示。' if rows else '没有美股持仓。旧版记录请在交易页编辑市场为 US。'))

    def update_quotes(self):
        if self.quote_running:
            return
        try:
            key = load_key(self.journal.path.parent)
        except OSError:
            self.quote_status.set('本机密钥无法读取，请在行情设置重新填写。')
            return
        self.quote_running = True
        self.quote_status.set('正在后台检查收盘行情；当前完整批次继续显示……')
        def worker():
            journal = None
            try:
                journal = Journal(self.journal.path)
                message = QuoteBook(journal).update(key, cancelled=self.quote_cancel.is_set)
            except Exception:
                message = '行情更新未完成，请检查网络、密钥或交易日历；旧行情已保留。'
            finally:
                if journal is not None:
                    journal.close()
            self.quote_queue.put(message)
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(150, self.poll_quotes)

    def poll_quotes(self):
        try:
            message = self.quote_queue.get_nowait()
        except queue.Empty:
            self.root.after(150, self.poll_quotes)
            return
        self.quote_running = False
        self.quote_status.set(message)
        self.render_positions()

    def backup(self):
        target = filedialog.asksaveasfilename(parent=self.root, title="备份交易日记", defaultextension=".sqlite3", initialfile=f"yaya-backup-{date.today()}.sqlite3", filetypes=[("日记备份", "*.sqlite3")])
        if target:
            try:
                self.journal.backup(target)
            except (OSError, sqlite3.Error, ValueError) as exc:
                messagebox.showerror("备份失败", str(exc), parent=self.root)
                return
            messagebox.showinfo("备份完成", "记录已备份到你选择的位置。", parent=self.root)

    def close(self):
        self.quote_cancel.set()
        self.journal.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true", help="Verify packaged UI and storage in a temporary directory")
    parser.add_argument("--data-dir", type=Path, help="Override local data folder")
    args = parser.parse_args()
    if args.smoke_test:
        with tempfile.TemporaryDirectory() as directory:
            root = tk.Tk()
            root.withdraw()
            app = App(root, Journal(Path(directory) / "smoke.sqlite3"))
            from quotes import target_session
            assert len(target_session()) == 10
            from key_store import protect
            import os
            if os.name == 'nt':
                assert protect(protect(b'test-only'), decrypt=True) == b'test-only'
            root.update_idletasks()
            app.fields['symbol'].set("TEST")
            app.fields['price'].set("12.50")
            app.fields['quantity'].set("2")
            app.save()
            assert len(app.journal.all()) == 1
            app.quote_book.update('fixture', target='2026-09-04', fetcher=lambda *args: {'2026-09-04':'11.25'}, pause=lambda _: None)
            app.show_positions()
            assert app.quote_book.snapshot()[0] == '2026-09-04'
            iid = app.tree.get_children()[0]
            app.tree.selection_set(iid)
            app.select()
            app.fields['price'].set("13.25")
            app.save()
            assert Decimal(app.journal.all()[0]['price']) == Decimal("13.25")
            app.journal.delete(int(iid))
            app.refresh()
            assert not app.tree.get_children()
            app.close()
        return
    root = tk.Tk()
    root.withdraw()
    try:
        journal = Journal(args.data_dir / "journal.sqlite3" if args.data_dir else None)
        App(root, journal)
    except (OSError, sqlite3.Error) as exc:
        messagebox.showerror("无法打开交易日记", f"无法读取本机记录：{exc}", parent=root)
        root.destroy()
        return
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()

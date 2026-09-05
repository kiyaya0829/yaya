"""Local transaction journal. Money is stored as decimal text, never floats."""
from datetime import date
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import re
import sqlite3

VERSION = "0.1.0"


def default_path():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return base / "YayaJournal" / "journal.sqlite3"


def validate(symbol, side, currency, price, quantity, traded_on, note):
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.^:/_-]{1,24}", symbol):
        raise ValueError("股票代码需为 1–24 位字母、数字或 . ^ : / _ -。")
    if side not in ("买入", "卖出"):
        raise ValueError("请选择买入或卖出。")
    if currency not in ("USD", "HKD", "CNY", "SGD", "EUR", "JPY", "GBP"):
        raise ValueError("请选择币种。")
    numbers = []
    for label, value in (("价格", price), ("数量", quantity)):
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            raise ValueError(f"{label}必须是有效数字。") from None
        if not number.is_finite() or number <= 0 or number >= Decimal("1000000000000"):
            raise ValueError(f"{label}必须大于 0 且小于一万亿。")
        if number.as_tuple().exponent < -8:
            raise ValueError(f"{label}最多支持 8 位小数。")
        numbers.append(format(number, "f"))
    try:
        parsed = date.fromisoformat(traded_on)
        if parsed.isoformat() != traded_on:
            raise ValueError()
    except ValueError:
        raise ValueError("日期格式应为 YYYY-MM-DD，且必须是有效日期。") from None
    if len(note) > 10000:
        raise ValueError("笔记最多 10,000 字。")
    return (symbol, side, currency, *numbers, traded_on, note.strip())


class Journal:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
            currency TEXT NOT NULL, price TEXT NOT NULL, quantity TEXT NOT NULL,
            traded_on TEXT NOT NULL, note TEXT NOT NULL)""")
        self.db.commit()

    def save(self, *, trade_id=None, **fields):
        values = validate(**fields)
        with self.db:
            if trade_id is None:
                return self.db.execute("""INSERT INTO trades
                    (symbol,side,currency,price,quantity,traded_on,note)
                    VALUES (?,?,?,?,?,?,?)""", values).lastrowid
            cursor = self.db.execute("""UPDATE trades SET symbol=?,side=?,currency=?,
                price=?,quantity=?,traded_on=?,note=? WHERE id=?""", (*values, trade_id))
            if cursor.rowcount != 1:
                raise ValueError("这条记录已不存在，请刷新后再试。")
            return trade_id

    def all(self, query=""):
        rows = self.db.execute("SELECT * FROM trades ORDER BY traded_on DESC, id DESC").fetchall()
        query = query.strip().casefold()
        return [row for row in rows if query in (row['symbol'] + ' ' + row['note']).casefold()]

    def delete(self, trade_id):
        with self.db:
            self.db.execute("DELETE FROM trades WHERE id=?", (trade_id,))

    def backup(self, destination):
        if Path(destination).resolve() == self.path.resolve():
            raise ValueError("备份请另存为其他文件，不要覆盖当前数据库。")
        with closing(sqlite3.connect(destination)) as target:
            self.db.backup(target)

    def close(self):
        self.db.close()

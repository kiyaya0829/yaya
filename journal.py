"""Local transaction journal. Money is stored as decimal text, never floats."""
from datetime import date
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import re
import sqlite3

VERSION = "0.3.0"


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
        if 'market' not in [r[1] for r in self.db.execute('PRAGMA table_info(trades)')]:
            with self.db:
                self.db.execute("ALTER TABLE trades ADD COLUMN market TEXT NOT NULL DEFAULT '待确认'")
        if 'fee' not in [r[1] for r in self.db.execute('PRAGMA table_info(trades)')]:
            with self.db:
                self.db.execute("ALTER TABLE trades ADD COLUMN fee TEXT NOT NULL DEFAULT '0'")

    def save(self, *, trade_id=None, market='待确认', fee='0', **fields):
        values = validate(**fields)
        try:
            fee = Decimal(str(fee).strip())
            if not fee.is_finite() or fee < 0 or fee >= Decimal('1e12') or fee.as_tuple().exponent < -8:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise ValueError('手续费需为非负数字，小于一万亿，最多 8 位小数。') from None
        fee = format(fee, 'f')
        if market not in ('US', '其他', '待确认'):
            raise ValueError('请选择市场。')
        if market == 'US' and (values[2] != 'USD' or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', values[0])):
            raise ValueError('美股需使用 USD 和有效美股代码，例如 AAPL、BRK.B。')
        with self.db:
            if trade_id is None:
                trade_id = self.db.execute("""INSERT INTO trades
                    (symbol,side,currency,price,quantity,traded_on,note,market,fee)
                    VALUES (?,?,?,?,?,?,?,?,?)""", (*values, market, fee)).lastrowid
            else:
                cursor = self.db.execute("""UPDATE trades SET symbol=?,side=?,currency=?,
                    price=?,quantity=?,traded_on=?,note=?,market=?,fee=? WHERE id=?""", (*values, market, fee, trade_id))
                if cursor.rowcount != 1:
                    raise ValueError("这条记录已不存在，请刷新后再试。")
            self.check_positions()
            return trade_id

    def check_positions(self):
        balances = {}
        for row in self.db.execute("SELECT * FROM trades WHERE market='US' ORDER BY traded_on,id"):
            key = row['symbol']
            balances[key] = balances.get(key, Decimal(0)) + Decimal(row['quantity']) * (1 if row['side'] == '买入' else -1)
            if balances[key] < 0:
                raise ValueError(f"{key} 的卖出数量超过此前已记录买入，请先补全买入记录（同日按录入顺序）。")

    def positions(self):
        balances = {}
        for row in self.db.execute("SELECT * FROM trades WHERE market='US' AND traded_on<=?", (date.today().isoformat(),)):
            key = row['symbol']
            balances[key] = balances.get(key, Decimal(0)) + Decimal(row['quantity']) * (1 if row['side'] == '买入' else -1)
        return {k: v for k, v in sorted(balances.items()) if v > 0}

    def all(self, query=""):
        rows = self.db.execute("SELECT * FROM trades ORDER BY traded_on DESC, id DESC").fetchall()
        query = query.strip().casefold()
        return [row for row in rows if query in (row['symbol'] + ' ' + row['note']).casefold()]

    def delete(self, trade_id):
        with self.db:
            self.db.execute("DELETE FROM trades WHERE id=?", (trade_id,))
            self.check_positions()

    def backup(self, destination):
        if Path(destination).resolve() == self.path.resolve():
            raise ValueError("备份请另存为其他文件，不要覆盖当前数据库。")
        with closing(sqlite3.connect(destination)) as target:
            self.db.backup(target)

    def close(self):
        self.db.close()

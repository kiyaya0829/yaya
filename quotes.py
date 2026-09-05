"""End-of-day quotes with persistent request budgeting and atomic publication."""
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, InvalidOperation
import json
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError


class QuoteError(Exception):
    pass


def target_session(now=None):
    # The calendar includes exchange holidays, early closes and DST.
    import exchange_calendars as xcals
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('UTC-aware time required')
    calendar = xcals.get_calendar('XNYS', start=str(now.year-1), end=f'{now.year+1}-12-31')
    schedule = calendar.schedule
    completed = schedule[schedule['close'] <= now]
    if completed.empty:
        raise QuoteError('无法确定已收市交易日，请稍后重试。')
    return completed.index[-1].date().isoformat()


def parse_daily(payload, symbol, target):
    series = payload.get('Time Series (Daily)') if isinstance(payload, dict) else None
    if not isinstance(series, dict):
        if isinstance(payload, dict) and ('Note' in payload or 'Information' in payload):
            raise QuoteError('数据商暂未提供数据：可能达到额度或密钥权限不足，请检查账号后稍后重试。')
        raise QuoteError('代码或 API Key 无效，或数据商返回格式异常。')
    metadata = payload.get('Meta Data', {})
    if str(metadata.get('2. Symbol', '')).upper() != symbol.upper():
        raise QuoteError('数据商返回的股票代码不匹配。')
    result = {}
    try:
        for day, values in series.items():
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
            if day > target:
                continue  # never accept an incomplete session
            price = Decimal(values['4. close'])
            if not price.is_finite() or price <= 0:
                raise ValueError()
            result[day] = format(price, 'f')
    except (ValueError, InvalidOperation, KeyError, TypeError):
        raise QuoteError('日线价格或日期无效，未保存此次响应。') from None
    return result


def fetch_daily(symbol, key, target):
    query = urlencode(dict(function='TIME_SERIES_DAILY', symbol=symbol, outputsize='compact', apikey=key))
    try:
        with urlopen('https://www.alphavantage.co/query?' + query, timeout=20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise QuoteError('行情响应过大，请稍后重试。')
        payload = json.loads(raw)
    except (URLError, OSError, ValueError):
        # Do not expose an exception containing the request URL/API key.
        raise QuoteError('网络连接或行情响应异常，旧报价已保留。') from None
    return parse_daily(payload, symbol, target)


class QuoteBook:
    def __init__(self, journal):
        self.journal = journal
        self.db = journal.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS closes(symbol TEXT, day TEXT, price TEXT NOT NULL,
                PRIMARY KEY(symbol,day));
            CREATE TABLE IF NOT EXISTS quote_requests(symbol TEXT, target TEXT, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS published_closes(day TEXT PRIMARY KEY);
        ''')

    def has(self, symbol, day):
        return self.db.execute('SELECT 1 FROM closes WHERE symbol=? AND day=?', (symbol, day)).fetchone() is not None

    def publish(self, target):
        with self.db:
            positions = self.journal.positions()
            if positions and all(self.has(symbol, target) for symbol in positions):
                self.db.execute('INSERT OR IGNORE INTO published_closes VALUES (?)', (target,))
                return True
        return False

    def snapshot(self):
        positions = self.journal.positions()
        if not positions:
            return None, []
        for row in self.db.execute('SELECT day FROM published_closes ORDER BY day DESC'):
            day = row[0]
            if all(self.has(symbol, day) for symbol in positions):
                return day, [(symbol, str(quantity), self.db.execute('SELECT price FROM closes WHERE symbol=? AND day=?', (symbol, day)).fetchone()[0]) for symbol, quantity in positions.items()]
        return None, [(symbol, str(quantity), '准备中') for symbol, quantity in positions.items()]

    def reserve(self, symbol, target, now):
        # Rolling 24h is conservative: no assumption about provider reset timezone.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            used = self.db.execute('SELECT count(*) FROM quote_requests WHERE at>?', (now-86400,)).fetchone()[0]
            if used >= 25:
                raise QuoteError('本机近 24 小时已使用 25 次请求；保留完整旧批次，额度恢复后再更新。')
            recent = self.db.execute('SELECT max(at) FROM quote_requests WHERE symbol=? AND target=?', (symbol, target)).fetchone()[0]
            if recent is not None and now-recent < 3600:
                self.db.rollback()
                return False
            self.db.execute('INSERT INTO quote_requests VALUES (?,?,?)', (symbol, target, now))
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def update(self, key, *, target=None, fetcher=fetch_daily, clock=time.time, pause=time.sleep, cancelled=lambda: False):
        positions = self.journal.positions()
        if not positions:
            return '没有需要更新的美股持仓；旧版记录请先确认市场。'
        if len(positions) > 25:
            return '持仓超过 25 只，超出当前免费方案每日整批更新能力；请调整数据方案，记录不会被删除。'
        target = target or target_session()
        missing = [symbol for symbol in positions if not self.has(symbol, target)]
        if missing and not key:
            return '请先在“行情设置”填写自己的 Alpha Vantage API Key。'
        error = ''
        requested = False
        for symbol in missing:
            if cancelled():
                return '已停止更新。'
            if requested:
                pause(1.1)
            try:
                if not self.reserve(symbol, target, clock()):
                    continue
                requested = True
                data = fetcher(symbol, key, target)
                with self.db:
                    self.db.executemany('INSERT OR REPLACE INTO closes VALUES (?,?,?)', [(symbol, day, price) for day, price in data.items()])
            except QuoteError as exc:
                error = str(exc)
                break
        if cancelled():
            return '已停止更新。'
        if self.publish(target):
            return f'全部持仓已统一至 {target} 收盘 · Alpha Vantage · USD · 未复权'
        current = self.journal.positions()
        done = sum(self.has(symbol, target) for symbol in current)
        return f'{target} 新行情 {done}/{len(current)}：尚未齐全，完整旧批次继续显示。' + (error or '数据商可能尚未更新；一小时后可重试。')

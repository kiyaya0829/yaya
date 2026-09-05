"""Date-aligned moving weighted-average cost accounting, all values in USD."""
from datetime import date
from decimal import Decimal, localcontext


def report(journal, as_of=None):
    as_of = as_of or date.today().isoformat()
    if date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError('日期应为 YYYY-MM-DD。')
    if as_of > date.today().isoformat():
        raise ValueError('不能使用未来日期。')
    with localcontext() as ctx:
        ctx.prec = 50
        accounts, details = {}, []
        for source in journal.db.execute('SELECT * FROM trades ORDER BY traded_on,id'):
            row = dict(source)
            row['included'] = row['market'] == 'US' and row['currency'] == 'USD' and row['traded_on'] <= as_of
            row['realized'] = None
            row['released_cost'] = None
            row['remaining_cost'] = None
            row['remaining_quantity'] = None
            row['reason'] = '计入' if row['included'] else ('晚于估值日' if row['traded_on'] > as_of else '非 US/USD 或市场待确认')
            details.append(row)
            if not row['included']:
                continue
            acc = accounts.setdefault(row['symbol'], dict(symbol=row['symbol'], quantity=Decimal(0), cost=Decimal(0), realized=Decimal(0), fees=Decimal(0)))
            q, price, fee = (Decimal(row[k]) for k in ('quantity','price','fee'))
            acc['fees'] += fee
            if row['side'] == '买入':
                acc['cost'] += q * price + fee
                acc['quantity'] += q
            else:
                if q > acc['quantity']:
                    raise ValueError(f"{row['symbol']} 的交易历史不完整，无法计算成本。")
                released = acc['cost'] if q == acc['quantity'] else acc['cost'] * q / acc['quantity']
                row['released_cost'] = released
                row['realized'] = q * price - fee - released
                acc['realized'] += row['realized']
                acc['cost'] -= released
                acc['quantity'] -= q
            row['remaining_cost'], row['remaining_quantity'] = acc['cost'], acc['quantity']
        rows = []
        for symbol, acc in sorted(accounts.items()):
            quote = journal.db.execute('SELECT price FROM closes WHERE symbol=? AND day=?', (symbol,as_of)).fetchone()
            close = Decimal(quote[0]) if quote else None
            acc['average'] = acc['cost'] / acc['quantity'] if acc['quantity'] else Decimal(0)
            acc['close'] = close
            acc['value'] = acc['quantity'] * close if close is not None else (Decimal(0) if not acc['quantity'] else None)
            acc['unrealized'] = acc['value'] - acc['cost'] if acc['value'] is not None else None
            acc['total'] = acc['realized'] + acc['unrealized'] if acc['unrealized'] is not None else None
            acc['status'] = '已清仓' if not acc['quantity'] else ('缺少当日收盘价' if close is None else '完整')
            rows.append(acc)
        totals = {key: sum((r[key] for r in rows), Decimal(0)) if all(r[key] is not None for r in rows) else None for key in ('cost','value','realized','unrealized','total','fees')}
        return dict(as_of=as_of, rows=rows, details=details, totals=totals, excluded=sum(not d['included'] for d in details))


def default_date(journal):
    row = journal.db.execute('SELECT max(day) FROM published_closes WHERE day<=?', (date.today().isoformat(),)).fetchone()
    return row[0] or date.today().isoformat()


def money(value):
    return '待补齐' if value is None else f'{value:,.2f}'

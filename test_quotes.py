from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest
from journal import Journal
from quotes import QuoteBook, QuoteError, parse_daily, target_session


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'journal.sqlite3'
        self.j = Journal(self.path)
        self.book = QuoteBook(self.j)
        self.now = 1000000

    def tearDown(self):
        self.j.close()
        self.tmp.cleanup()

    def trade(self, symbol='AAPL', side='买入', quantity='2', **extra):
        return self.j.save(symbol=symbol, side=side, currency='USD', price='100', quantity=quantity,
                           traded_on='2020-01-02', note='', market='US', **extra)

    def update(self, fetcher, target='2026-09-04'):
        return self.book.update('fake', target=target, fetcher=fetcher, clock=lambda: self.now, pause=lambda _: None)

    def test_partial_sale_clear_and_rebuy_keep_history(self):
        self.trade()
        self.trade(side='卖出', quantity='1')
        self.assertEqual(self.j.positions(), {'AAPL': Decimal(1)})
        self.trade(side='卖出', quantity='1')
        self.assertEqual(self.j.positions(), {})
        self.update(lambda *args: self.fail('cleared position fetched'))
        self.trade(quantity='3')
        self.assertEqual(self.j.positions(), {'AAPL': Decimal(3)})
        self.assertEqual(len(self.j.all()), 4)

    def test_oversell_and_invalid_buy_delete_roll_back(self):
        buy = self.trade()
        self.trade(side='卖出', quantity='1')
        with self.assertRaises(ValueError):
            self.trade(side='卖出', quantity='2')
        with self.assertRaises(ValueError):
            self.j.delete(buy)
        self.assertEqual(len(self.j.all()), 2)
        self.assertEqual(self.j.positions()['AAPL'], 1)

    def test_partial_batch_is_never_published_and_resumes_after_restart(self):
        self.trade()
        self.trade('MSFT')
        self.update(lambda *args: {'2026-09-03':'100'}, target='2026-09-03')
        self.assertEqual(self.book.snapshot()[0], '2026-09-03')
        def partial(symbol, *_):
            if symbol == 'MSFT':
                raise QuoteError('offline')
            return {'2026-09-04':'101'}
        self.update(partial)
        self.assertEqual(self.book.snapshot()[0], '2026-09-03')
        self.j.close()
        self.j = Journal(self.path)
        self.book = QuoteBook(self.j)
        self.now += 3601
        calls = []
        self.update(lambda symbol, *_: calls.append(symbol) or {'2026-09-04':'102'})
        self.assertEqual(calls, ['MSFT'])
        day, rows = self.book.snapshot()
        self.assertEqual(day, '2026-09-04')
        self.assertEqual([r[2] for r in rows], ['101', '102'])
        self.update(lambda *args: self.fail('cached target refetched'))

    def test_first_batch_pending_and_new_position_hides_incomplete_snapshot(self):
        self.trade()
        self.assertIsNone(self.book.snapshot()[0])
        self.update(lambda *args: {'2026-09-04':'100'})
        self.trade('MSFT')
        self.assertIsNone(self.book.snapshot()[0])
        self.assertTrue(all(row[2] == '准备中' for row in self.book.snapshot()[1]))

    def test_budget_cooldown_and_more_than_25_holdings(self):
        self.trade()
        with self.j.db:
            self.j.db.executemany('INSERT INTO quote_requests VALUES (?,?,?)', [('OTHER','2026-09-04',self.now)]*25)
        self.assertIn('25', self.update(lambda *args: self.fail('over budget')))
        self.now += 86401
        self.update(lambda *args: {})
        self.update(lambda *args: self.fail('cooldown ignored'))
        for n in range(25):
            self.trade('S'+str(n))
        self.assertIn('超过 25', self.update(lambda *args: self.fail('oversized batch requested')))
        self.assertEqual(len(self.j.positions()), 26)

    def test_cleared_symbol_history_remains(self):
        self.trade()
        self.update(lambda *args: {'2026-09-04':'100'})
        self.trade(side='卖出')
        self.assertTrue(self.book.has('AAPL', '2026-09-04'))
        self.assertEqual(self.book.snapshot(), (None, []))

    def test_parser_rejects_wrong_symbol_bad_prices_and_future(self):
        payload = {'Meta Data': {'2. Symbol':'AAPL'}, 'Time Series (Daily)': {'2026-09-04': {'4. close':'123.45'}, '2026-09-08': {'4. close':'999'}}}
        self.assertEqual(parse_daily(payload,'AAPL','2026-09-04'), {'2026-09-04':'123.45'})
        with self.assertRaises(QuoteError):
            parse_daily(payload,'MSFT','2026-09-04')
        for price in ['NaN','-1','0','bad']:
            payload['Time Series (Daily)']['2026-09-04']['4. close'] = price
            with self.assertRaises(QuoteError):
                parse_daily(payload,'AAPL','2026-09-04')
        for payload in [{'Information':'rate limit'}, {'Error Message':'invalid'}, {}]:
            with self.assertRaises(QuoteError):
                parse_daily(payload,'AAPL','2026-09-04')


class MigrationTests(unittest.TestCase):
    def test_old_schema_is_preserved_without_guessing_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'old.sqlite3'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE trades(id INTEGER PRIMARY KEY,symbol TEXT,side TEXT,currency TEXT,price TEXT,quantity TEXT,traded_on TEXT,note TEXT)')
            db.execute("INSERT INTO trades VALUES(1,'AAPL','买入','USD','10','2','2020-01-02','old note')")
            db.commit()
            db.close()
            j = Journal(path)
            try:
                self.assertEqual(j.all()[0]['note'], 'old note')
                self.assertEqual(j.all()[0]['market'], '待确认')
                self.assertEqual(j.positions(), {})
            finally:
                j.close()


class CalendarTests(unittest.TestCase):
    def test_weekend_holiday_early_close_and_dst(self):
        cases = {
            '2026-09-07T18:00:00+00:00':'2026-09-04',  # Labor Day
            '2026-09-06T12:00:00+00:00':'2026-09-04',
            '2026-11-27T17:59:00+00:00':'2026-11-25',  # Thanksgiving early close
            '2026-11-27T18:01:00+00:00':'2026-11-27',
            '2026-03-06T20:30:00+00:00':'2026-03-05',  # winter 21 UTC
            '2026-03-09T20:01:00+00:00':'2026-03-09',  # summer 20 UTC
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(target_session(datetime.fromisoformat(value)), expected)


if __name__ == '__main__':
    unittest.main()

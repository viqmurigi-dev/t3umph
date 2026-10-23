"""
Polymarket BTC hourly "Up or Down" bot #3  --  PAPER TRADING ONLY.

Every hourly market:
  * Split 2/5 of capital into equal Up + Down shares (1 USD -> 1 Up + 1 Down)
    and post limit SELLs on BOTH sides at 0.55.
  * STOP LOSS: any side still unsold whose best bid falls to 0.35 is sold.
    Both sides at 0.55 = +10% of the stake; one side at 0.55 plus the other
    stopped at 0.35 = -10% of the stake. That is the 1:1 risk:reward.
  * Anything not sold by either price is held to resolution (pays 1.00 / 0.00).

Sizing:
  normal : 2/5 of capital
  after a stop loss was hit: the next hour's stake is the SAME as the stake of
           the hour where the stop was hit (not recalculated from the smaller capital)
  doji   : if the last Binance BTCUSDT 1h candle is a doji (body <= 20% of its
           high-low range) AND the candle before it was NOT a doji, the next
           hour's stake is 2x the normal stake. Further dojis in a row do NOT
           re-trigger it. The doji rule beats the stop-loss rule if both apply.
  A stake is always capped at free cash.

Logs (next to this file):
  bot3_trades.csv  one row per finished hour, incl. how each side was sold
  bot3_sells.csv   one row per SELL (55c limit, 35c stop, or resolution)
  bot3_state.json  lets the bot resume after a restart

Resolution (per Polymarket's rules for these markets): Binance BTC/USDT 1H
candle, Up if close >= open. Fees are ignored. No real orders are sent.
Paper fills: a resting 0.55 sell fills when the best bid >= 0.55 (polled, so
brief spikes can be missed). The stop sells at the current best bid (<= 0.35).
"""
import csv
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
ET = ZoneInfo("America/New_York")
BASE = os.path.dirname(os.path.abspath(__file__))   # logs/state live next to this file
SIDES = ("up", "down")

CONFIG = {
    "starting_capital": 1000.0,
    "base_fraction": 2 / 5,        # normal stake = this share of capital
    "doji_multiplier": 2.0,        # stake after a doji = this x the normal stake
    "sell_price": 0.55,
    "stop_price": 0.35,            # stop loss: an unsold side whose best bid falls to this is sold
    "stop_after_minutes": 0,       # 0 = the stop is active from the moment the hour opens
    "pre_start_seconds": 300,      # enter 5 min before the hour. The previous candle is still forming then,
                                   # so the doji rule uses its state at that moment (approximate).
                                   # 0 = wait for the previous candle to CLOSE, then enter.
    "poll_seconds": 3,
    "doji_body_max": 0.20,         # a candle is a doji when |close-open| <= this share of (high-low)
    "resolve_fallback_minutes": 15,     # if Polymarket hasn't resolved this long after the hour, use Binance's candle (None = never)
    "wait_prior_settle_seconds": 180,   # wait this long after the hour opens for last round's cash
    "start_timeout_seconds": 60,   # a round may start at most this long AFTER the hour opens; later = skip the hour
    "retry_seconds": 15,           # how often to retry candle/market lookups while starting a round
    "min_stake": 5.0,              # skip rounds smaller than this (Polymarket has a 5-share minimum)
    "binance_url": "https://api.binance.com",   # use https://api.binance.us if blocked
    "trade_log": os.path.join(BASE, "bot3_trades.csv"),
    "sell_log": os.path.join(BASE, "bot3_sells.csv"),
    "state_file": os.path.join(BASE, "bot3_state.json"),   # lets the bot resume after a restart
}


# ------------------------------------------------------------ data sources
class PolymarketData:
    def find_btc_hourly(self, start):
        start_et = start.astimezone(ET)          # market names/slugs are in ET
        end_utc = (start + timedelta(hours=1)).astimezone(timezone.utc)
        hour12 = start_et.strftime("%I").lstrip("0") + start_et.strftime("%p").lower()
        slug = (f"bitcoin-up-or-down-{start_et.strftime('%B-%d-%Y').lower().replace('-0', '-')}"
                f"-{hour12}-et")
        try:
            r = requests.get(f"{GAMMA}/events/slug/{slug}", timeout=15)
            if r.ok:
                m = self._pick_market(r.json())
                if m:
                    return m
        except Exception:
            pass
        try:
            r = requests.get(f"{GAMMA}/public-search",
                             params={"q": "Bitcoin Up or Down", "limit_per_type": 50}, timeout=15).json()
            for ev in r.get("events", []):
                end = datetime.fromisoformat(ev["endDate"].replace("Z", "+00:00"))
                title = ev.get("title", "").lower()
                # hourly titles have no clock times with ":" (15-minute markets do, e.g. 12:45PM-1:00PM)
                if ("bitcoin" in title and ":" not in title
                        and abs((end - end_utc).total_seconds()) < 120):
                    m = self._pick_market(ev)
                    if m:
                        return m
        except Exception:
            pass
        return None

    @staticmethod
    def _pick_market(ev):
        for m in ev.get("markets", []):
            try:
                tokens = m["clobTokenIds"]
                tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
                outcomes = m.get("outcomes", '["Up","Down"]')
                outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
                names = [o.lower() for o in outcomes]
                return {"question": m.get("question", ev.get("title")), "slug": m.get("slug"),
                        "up_token": tokens[names.index("up")], "down_token": tokens[names.index("down")]}
            except Exception:
                continue
        return None

    def best_bid(self, token_id):
        try:
            book = requests.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=10).json()
            bids = [float(b["price"]) for b in book.get("bids", [])]
            return max(bids) if bids else None
        except Exception:
            return None

    def resolution(self, slug):
        """{'up': 1/0, 'down': 1/0} once resolved, else None."""
        try:
            r = requests.get(f"{GAMMA}/markets/slug/{slug}", timeout=15).json()
            prices = r.get("outcomePrices")
            prices = json.loads(prices) if isinstance(prices, str) else prices
            outcomes = r.get("outcomes")
            outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            p = {o.lower(): float(x) for o, x in zip(outcomes, prices)}
            if r.get("closed") and max(p.values()) >= 0.99:
                return {"up": round(p["up"]), "down": round(p["down"])}
        except Exception:
            pass
        return None


class BinanceCandles:
    def __init__(self, base_url):
        self.base = base_url
        self.last_error = None

    def hourly(self):
        """{open_time_ms: {o,h,l,c,close_time}} for the latest few 1h BTCUSDT candles."""
        self.last_error = None
        try:
            resp = requests.get(f"{self.base}/api/v3/klines",
                                params={"symbol": "BTCUSDT", "interval": "1h", "limit": 24}, timeout=10)
            if not resp.ok:
                hint = (" (Binance is blocked from your location; set binance_url to https://api.binance.us)"
                        if resp.status_code in (403, 451) else "")
                self.last_error = f"Binance returned HTTP {resp.status_code}{hint}"
                return {}
            return {int(k[0]): {"o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
                                "c": float(k[4]), "close_time": int(k[6])} for k in resp.json()}
        except Exception as e:
            self.last_error = f"could not reach Binance ({type(e).__name__})"
            return {}


# ------------------------------------------------------------ rules helpers
def hhmm(t):
    return t.astimezone(ET).strftime("%H:%M")


def compute_stake(capital, cash, prev_round, doji, cfg):
    """Return (stake, reason). The stake never exceeds free cash.
      normal : base_fraction x capital                         (2/5)
      stop   : the previous hour hit a stop loss -> the previous hour's stake, unchanged
      doji   : doji_multiplier x the normal stake              (2 x 2/5)
    The doji rule takes priority over the stop-loss rule."""
    base = cfg["base_fraction"] * capital
    if doji:
        stake, why = cfg["doji_multiplier"] * base, f"doji after non-doji: {cfg['doji_multiplier']:g}x normal (capital ${capital:,.0f})"
    elif prev_round is not None and prev_round.sl_hit():
        stake, why = prev_round.stake, f"after stop loss: same stake as previous hour (${prev_round.stake:,.2f})"
    else:
        stake, why = base, f"normal (capital ${capital:,.0f})"
    return min(stake, cash), why


def body_share(c):
    rng = c["h"] - c["l"]
    return None if rng <= 0 else abs(c["c"] - c["o"]) / rng


def is_doji(c, cfg):
    """Doji = tiny body relative to the candle's range. A candle with no range counts as a doji."""
    bs = body_share(c)
    return True if bs is None else bs <= cfg["doji_body_max"]


def doji_rule_triggered(prev, last, cfg):
    """last = most recent candle, prev = the one before. A doji right after a non-doji."""
    return is_doji(last, cfg) and not is_doji(prev, cfg)


# ------------------------------------------------------------ paper round
@dataclass
class Round:
    start: datetime
    mkt: dict
    stake: float                  # USD split = shares per side
    sell_price: float
    why: str
    sold: dict = field(default_factory=lambda: {"up": False, "down": False})      # filled at sell_price
    stopped: dict = field(default_factory=lambda: {"up": False, "down": False})   # sold by rule 2
    proceeds: float = 0.0
    last_res_check: float = 0.0
    done: bool = False
    # how each side was sold: {"kind": "55c limit" | "35c stop" | "resolution", "price": float, "t": iso time}
    exits: dict = field(default_factory=lambda: {"up": None, "down": None})

    @property
    def end(self):
        return self.start + timedelta(hours=1)

    def to_dict(self):
        d = asdict(self)
        d["start"] = self.start.isoformat()
        return d

    @staticmethod
    def from_dict(d):
        d = dict(d)
        d["start"] = datetime.fromisoformat(d["start"])
        d["last_res_check"] = 0.0
        return Round(**d)

    def sl_hit(self):
        """True if a stop loss sold either side of this round."""
        return any(self.stopped.values())

    def holding(self, side):
        return not (self.sold[side] or self.stopped[side])

    def has_holdings(self):
        return any(self.holding(s) for s in SIDES)


# ------------------------------------------------------------ the bot
class Bot:
    def __init__(self, data=None, candles=None, cfg=None):
        self.cfg = cfg or CONFIG
        self.data = data or PolymarketData()
        self.candles = candles or BinanceCandles(self.cfg["binance_url"])
        self.cash = self.cfg["starting_capital"]
        self.rounds = []          # active + finished
        self.next_start = None
        self._last_attempt = 0.0
        self._last_snap = None
        self._warned = set()
        self._pending_rows = []   # finished-round rows waiting to be written to the trades CSV
        self._pending_sells = []  # sell rows waiting to be written to the sells CSV
        self._blocked = set()     # log files that are currently locked
        self._load()

    def _warn_once(self, key, msg):
        """Print a warning once per (hour, reason) so a stuck lookup is visible but not spammy."""
        if key not in self._warned:
            self._warned.add(key)
            print(f"[warn] {msg}")

    def capital(self):
        """Total capital: free cash plus the cost basis (50c per share) of any still-unsold shares in open rounds."""
        locked = sum(0.5 * r.stake * sum(r.holding(s) for s in SIDES) for r in self.rounds if not r.done)
        return self.cash + locked

    # -------- save/restore so a restart doesn't lose the paper account
    def _save(self):
        path = self.cfg.get("state_file")
        if not path:
            return
        snap = json.dumps({
            "cash": self.cash,
            "next_start": self.next_start.isoformat() if self.next_start else None,
            "rounds": [r.to_dict() for r in self.rounds[-3:]],   # recent rounds are enough
        })
        if snap == self._last_snap:
            return
        try:
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                f.write(snap)
            os.replace(tmp, path)
            self._last_snap = snap
            self._save_blocked = False
        except OSError as e:                       # e.g. antivirus briefly locking the file; try again next tick
            if not getattr(self, "_save_blocked", False):
                self._save_blocked = True
                print(f"[warn] could not save {os.path.basename(path)} ({e}); will keep retrying")

    def _load(self):
        path = self.cfg.get("state_file")
        if not path or not os.path.exists(path):
            return
        try:
            with open(path) as f:
                s = json.load(f)
            self.cash = s["cash"]
            self.rounds = [Round.from_dict(d) for d in s["rounds"]]
            self.next_start = datetime.fromisoformat(s["next_start"]) if s["next_start"] else None
            print(f"Restored saved state: cash ${self.cash:.2f}, "
                  f"{sum(not r.done for r in self.rounds)} open round(s)")
        except Exception as e:
            print(f"[warn] could not load saved state ({e}); starting fresh")

    # -------- main step, called repeatedly
    def tick(self, now):
        now = now.astimezone(timezone.utc)   # all hour arithmetic in UTC (safe across DST changes)
        if (self.next_start is not None
                and now > self.next_start + timedelta(seconds=self.cfg["start_timeout_seconds"])):
            print(f"[{hhmm(self.next_start)}] missed the start window (or bot was down), resyncing to the next hour.")
            self.next_start = None
        if self.next_start is None:
            ns = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            while any(r.start == ns for r in self.rounds):      # never open the same hour twice
                ns += timedelta(hours=1)
            self.next_start = ns
        for r in self.rounds:
            if not r.done:
                self._manage(r, now)
        self._maybe_start(now)
        self._flush_log()
        self._save()

    def _manage(self, r, now):
        c = self.cfg
        if now < r.end:
            if not r.has_holdings():
                return                                   # both sides already sold: nothing left to watch
            bids = {"up": self.data.best_bid(r.mkt["up_token"]),
                    "down": self.data.best_bid(r.mkt["down_token"])}
            for s in SIDES:
                if r.holding(s) and bids[s] is not None and bids[s] >= r.sell_price:
                    r.sold[s] = True
                    self._record_sell(r, s, f"{r.sell_price * 100:.0f}c limit", r.sell_price, now)
            # stop loss: an unsold side whose best bid falls to stop_price is sold (only once the hour is open)
            if now >= r.start + timedelta(minutes=c["stop_after_minutes"]):
                for s in SIDES:
                    b = bids[s]
                    if r.holding(s) and b is not None and b <= c["stop_price"]:
                        r.stopped[s] = True
                        self._record_sell(r, s, f"{c['stop_price'] * 100:.0f}c stop", b, now)
            return
        # hour is over
        if not r.has_holdings():
            return self._finish(r, None)
        if time.time() - r.last_res_check < 15:
            return
        r.last_res_check = time.time()
        res = self.data.resolution(r.mkt["slug"])
        fb = c.get("resolve_fallback_minutes")
        if res is None and fb and now >= r.end + timedelta(minutes=fb):
            res = self._binance_result(r, now)       # Polymarket is slow to resolve: use the same Binance candle
            if res is not None:
                print(f"  [{hhmm(r.start)}] Polymarket has not resolved after {fb} min; "
                      f"using the Binance 1h candle result instead")
        if res is None:
            return
        for s in SIDES:
            if r.holding(s):
                self._record_sell(r, s, "resolution", float(res[s]), now)
        self._finish(r, res)

    def _record_sell(self, r, side, kind, price, now):
        """Credit the proceeds, remember how this side was sold, print it and queue it for bot3_sells.csv."""
        proceeds = r.stake * price
        r.proceeds += proceeds
        self.cash += proceeds
        t = now.astimezone(ET).isoformat()
        r.exits[side] = {"kind": kind, "price": round(price, 4), "t": t}
        print(f"  [{hhmm(r.start)}] sold {side} at {price:.2f} ({kind}) -> ${proceeds:,.2f}")
        self._pending_sells.append([r.start.astimezone(ET).isoformat(), r.mkt["question"], side, kind,
                                    round(price, 4), round(r.stake, 2), round(proceeds, 2), t])

    def _binance_result(self, r, now):
        """Up/Down from the Binance 1h candle that opened at the round's start (Polymarket's own rule)."""
        cs = self.candles.hourly()
        cd = cs.get(int(r.start.timestamp() * 1000))
        if cd is None or cd["close_time"] >= int(now.timestamp() * 1000):
            return None
        return {"up": 1, "down": 0} if cd["c"] >= cd["o"] else {"up": 0, "down": 1}

    def _finish(self, r, res):
        r.done = True
        winner = "n/a" if res is None else ("up" if res["up"] else "down")
        pnl = r.proceeds - r.stake
        print(f"  [{hhmm(r.start)}] done: winner={winner} up_sold={r.sold['up']} down_sold={r.sold['down']} "
              f"stopped={[s for s in SIDES if r.stopped[s]]} PnL ${pnl:+.2f} | cash ${self.cash:.2f}")
        ex = lambda side, key: (r.exits.get(side) or {}).get(key, "")
        self._pending_rows.append([r.start.astimezone(ET).isoformat(), r.mkt["question"], round(r.stake, 2), r.why,
                                   ex("up", "kind"), ex("up", "price"), ex("down", "kind"), ex("down", "price"),
                                   "yes" if r.sl_hit() else "no",
                                   winner, round(r.proceeds, 2), round(pnl, 2), round(self.cash, 2)])
        self._flush_log()

    TRADE_HEADER = ["start_et", "question", "stake", "why", "up_exit", "up_exit_price", "down_exit",
                    "down_exit_price", "stop_loss_hit", "winner", "proceeds", "pnl", "cash_after"]
    SELL_HEADER = ["round_start_et", "question", "side", "sold_at", "price", "shares", "proceeds", "time_et"]

    def _flush_log(self):
        """Write queued rows to the CSV files. If a file is locked (e.g. open in Excel) keep the rows and retry."""
        for attr, path, header in (("_pending_rows", self.cfg["trade_log"], self.TRADE_HEADER),
                                   ("_pending_sells", self.cfg["sell_log"], self.SELL_HEADER)):
            rows = getattr(self, attr)
            if not rows:
                continue
            try:
                new = not os.path.exists(path)
                with open(path, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(header)
                    w.writerows(rows)
                setattr(self, attr, [])
                self._blocked.discard(path)
            except OSError as e:
                if path not in self._blocked:
                    self._blocked.add(path)
                    print(f"[warn] cannot write {os.path.basename(path)} ({e}); close it in Excel. "
                          f"{len(rows)} row(s) are queued and will be saved automatically.")

    def _maybe_start(self, now):
        c = self.cfg
        start = self.next_start
        if now < start - timedelta(seconds=c["pre_start_seconds"]):
            return
        # let the previous round's cash come back if it is only waiting for resolution
        waiting = any(not r.done and now >= r.end for r in self.rounds)
        if waiting and now < start + timedelta(seconds=c["wait_prior_settle_seconds"]):
            return

        # don't hammer Binance/Gamma every poll while waiting for data
        if time.time() - self._last_attempt < c["retry_seconds"]:
            return
        self._last_attempt = time.time()

        # --- rule 3 inputs: last two candles
        now_ms = int(now.timestamp() * 1000)
        k = int((start - timedelta(hours=1)).timestamp() * 1000)
        kprev = int((start - timedelta(hours=2)).timestamp() * 1000)
        cs = self.candles.hourly()
        last, prev = cs.get(k), cs.get(kprev)
        if last is None or prev is None:
            err = getattr(self.candles, "last_error", None) or "the needed 1h candles are not in the response yet"
            self._warn_once((start, "candles", err), f"[{hhmm(start)}] waiting on candle data: {err}")
            return                                       # retry next tick
        if c["pre_start_seconds"] == 0 and last["close_time"] >= now_ms:
            return                                       # candle not closed yet; retry

        mkt = self.data.find_btc_hourly(start)
        if not mkt:
            self._warn_once((start, "market"), f"[{hhmm(start)}] could not find the Polymarket BTC hourly market "
                            f"yet (it may not be listed or the name format changed); retrying")
            return                                       # retry until timeout

        # --- sizing
        prior = next((r for r in self.rounds if r.start == start - timedelta(hours=1)), None)
        stake, why = compute_stake(self.capital(), self.cash, prior,
                                   doji=doji_rule_triggered(prev, last, c), cfg=c)
        if stake < c["min_stake"]:
            print(f"[{hhmm(start)}] stake ${stake:.2f} is below the minimum, skipping this hour.")
            self.next_start = start + timedelta(hours=1)
            return

        print(f"[{hhmm(start)}] Market: {mkt['question']}")
        print(f"  Split ${stake:.2f} ({why}); selling both sides at {c['sell_price']:.2f}")
        self.cash -= stake
        self.rounds.append(Round(start=start, mkt=mkt, stake=stake, sell_price=c["sell_price"], why=why))
        self.next_start = start + timedelta(hours=1)


def run():
    try:                                   # Windows consoles can choke on unusual characters in market names
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    bot = Bot()
    print(f"Paper mode - BOT 3 ({CONFIG['stop_price'] * 100:.0f}c stop loss). "
          f"Capital ${bot.capital():.2f}. Ctrl+C to stop.")
    try:
        while True:
            try:
                bot.tick(datetime.now(timezone.utc))
            except KeyboardInterrupt:
                raise
            except Exception as e:                      # one bad API response must not kill the bot
                print(f"[warn] tick failed: {type(e).__name__}: {e}")
            time.sleep(CONFIG["poll_seconds"])
    except KeyboardInterrupt:
        locked = sum(r.stake for r in bot.rounds if not r.done)
        print(f"\nStopped. Cash ${bot.cash:.2f} (+ up to ${locked:.2f} still in open rounds)")


if __name__ == "__main__":
    run()

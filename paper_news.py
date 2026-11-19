"""
PAPER TRADER: 55c HEDGE ON THE NEWS-RELEASE HOURS + THE US OPEN.          *** NO REAL ORDERS: it only READS public Polymarket data. ***

WHAT IT TRADES (BTC "Up or Down" markets, all times shown in NAIROBI time (EAT, UTC+3) and New York time)
  NEWS   CPI, PPI and jobs report (NFP) at 08:30 ET, FOMC decision at 14:00 ET.  For each release day, three streams:
           hourly   6 hourly candles: 06:00-12:00 ET (CPI/PPI/NFP) or 12:00-18:00 ET (FOMC)      -> 14:00-20:00 Nairobi in US winter time, 13:00-19:00 in summer time
           4-hour   the 4h candle that contains the release (08:00-12:00 ET, FOMC: 12:00-16:00 ET)
           daily    the daily candle that contains the release (noon-to-noon ET)
  OPEN   the 09:00-10:00 ET hourly candle on weekdays that are NOT release days (US stock open; also skipped on US market holidays). No recovery.

THE TRADE (the "55c hedge", per candle)
  5 MINUTES BEFORE the candle opens the stake is SPLIT into a pair ($1 -> 1 Up + 1 Down share, free) and a LIMIT SELL at 55c is placed on each leg.
  both legs sell  -> +$0.10 per $1 of pair.   one leg sells and the other loses -> -$0.45.   one sells and the other wins -> +$0.55.   none sells -> $0.
  A leg counts as sold when the real best BID reaches 55c (strict, main result "bid"). The column pnl_mid shows the looser "mid price reached 55c" rule for comparison.
  A candle that follows one with a leg sold but not yet resolved waits for that result (it can turn into a loss that sets the recovery stake), so it is placed a little after the open.
  FEES (Polymarket crypto markets, docs.polymarket.com): a resting limit order that gets filled is a MAKER: no fee, and it earns a rebate = 20% of the fee equivalent
  N x 0.07 x p x (1-p) (about 0.7% of the stake per hedged pair).  If the best bid is already >= 55c when the order is placed it sells at once as a TAKER at that bid and pays 0.07 x p x (1-p) per share, with no rebate.
  The rebates accrue per fill and are paid once a day (credited to cash when the unpaid balance reaches $1, as Polymarket does); paper_news_rebates.log / .csv report each 24 hours at 00:00 Nairobi time.
  DAILY PNL UPDATE: at the same 00:00 Nairobi cut the bot logs (and sends to your phone if ntfy is on) the day's trades, PnL, rebate, equity and recovery owed -> paper_news_daily.log / .csv.

MONEY RULES   start $100, stake = 20% of your FREE cash (money not locked in open trades) per candle.  Option base=total: 20% of TOTAL capital instead (money locked in open trades included),
  but never more than the free cash.
  RECOVERY (news HOURLY candles only): after a loss L the NEXT hourly candle stakes 10 x L (it earns +10% when it hedges, so it wins L back), capped at 100% of free cash (cap=1.0: the whole free cash can go into one recovery candle; use cap=0.5 for a safer limit).
  Recovery lasts ONE candle: whatever it does not win back, or loses, is taken as a realised loss (no chasing on later candles). The 7th hourly candle is traded only if the 6th candle was a loss.
  The 4-hour and daily candles and the US open have NO recovery: in the backtest recovery lowered the 4h result and changed the daily one by almost nothing (option recov_tfs=1h,4h,1d to change).

NEWS LISTENER (runs in the background while the bot runs)
  - checks the release calendar online at start and every 6 hours (BLS schedule pages + Federal Reserve calendar) and raises an ALERT if a date is new or no longer confirmed,
  - warns 60 minutes and 5 minutes before the first trade of every release day, and when the release time arrives,
  - after each 08:30 release it checks the BLS release page and tells you if the report was published or NOT (postponement, shutdown),
  - warns when the calendar is about to run out, and sends every alert to your phone if you give  ntfy=<topic>  (free app ntfy.sh).
  The built-in calendar covers every 2026 release, BLS releases to April 2027 and the 2027 FOMC meetings; the listener fills in the rest online. For other dates, put them in calendar.json:
      {"add": [{"date": "2027-01-08", "kind": "NFP"}], "remove": ["2026-12-04"], "holidays": ["2027-01-18"]}

RUN (leave the window open; PC awake. You can stop with Ctrl+C and restart: it continues from paper_news_state.json)
  py paper_news.py selftest             offline test with fake markets
  py paper_news.py schedule             the next 45 days of trades in Nairobi time          (days=60 for longer)
  py paper_news.py calendar             refresh the calendar online and show what changed
  py paper_news.py run                  start paper trading          options: capital=100 stake=0.20 cap=1.00 poll=2 lead=300 minstake=5 base=free|total ntfy=<topic> open=1 recovery=1 rebate=0.20 rebate_hour=0
  py paper_news.py notifytest ntfy=<topic>   send a test message to your phone
  py paper_news.py status               equity, open trades, next trades
  py paper_news.py summary              results + the go / no-go checks  -> paper_news_summary.txt
Files: paper_news_trades.csv (one row per trade), paper_news_daily.log + .csv (daily PnL update), paper_news_rebates.log + .csv (daily maker-rebate report), paper_news_state.json, paper_news.log, calendar.json (yours), calendar_cache.json
To start over with a fresh $100: stop the bot and delete paper_news_state.json (and paper_news_trades.csv).

LIMITS: a paper fill is not a real fill: no queue position, no partial fills (the bid size at the touch is logged in size_ok), polling every 2 seconds can miss a very brief touch.
A candle that follows an unresolved one waits up to 3 minutes for the result (needed for the recovery stake), then trades late (logged in late_s).

EARLY ORDERS + SLEEP (early=1 default; rest=1 is for GitHub Actions, wake=6000 s = 100 min):
  early: when a candle has completed its hedge (both 55c legs sold) and the NEXT hourly candle of the same news block is a normal scheduled one, its orders go in at once,
         not 5 minutes before the open. If the candle before did not hedge (or one leg is sold and the result is awaited) the usual 5-minute / wait-for-result rule applies.
  rest:  between candles the bot simply stays in its run and waits (cheap). Only when the next thing to do is more than wake+10 min away does it exit, and the workflow starts it again `wake` seconds before.
         (GitHub's schedule can be late or run only about hourly, so the restart is early enough to survive that.)
         Open trades keep their orders in the saved state; on waking their fills are re-checked from the real trades (so a 55c sell that filled while it slept is found).
  Market names tried: bitcoin-up-or-down-<month>-<day>-<year>-<hour>-et (1h), btc-updown-4h-<start epoch>, btc-updown-1d-<start epoch> (and older name styles);
  a market is accepted only if its end date matches the candle (a name can repeat from one year to the next).

BACK-FILL (on by default; backfill=0 turns it off, bf_days=5 how far back, default 5 days):
  If the computer was off when a scheduled candle ran, the bot rebuilds it on the next start from Polymarket's REAL executed trades:
  a side counts as sold when someone bought it at 55c or more after the orders would have gone in. Stakes, recovery (10x on the next candle)
  and cash are applied in time order, as if the trades had been taken. Rows are marked source=backfill in the CSV.
  Limit: queue position is ignored, so back-filled fills are a little optimistic. Candles from before the first ever start are never back-filled.
"""
import csv
import heapq
import json
import math
import os
import re
import sys
import threading
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from html import unescape
from zoneinfo import ZoneInfo

UTC, ET, KE = timezone.utc, ZoneInfo("America/New_York"), ZoneInfo("Africa/Nairobi")
HERE = os.path.dirname(os.path.abspath(__file__))
GAMMA, CLOB = "https://gamma-api.polymarket.com", "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
FEE = 0.07
TARGET = 0.55
BREAK_EVEN = 0.818                  # hedge rate needed for +EV (hedged +0.10, one-leg miss -0.45)
TRADES_CSV = os.path.join(HERE, "paper_news_trades.csv")
STATE_JSON = os.path.join(HERE, "paper_news_state.json")
LOG_FILE = os.path.join(HERE, "paper_news.log")
CAL_USER = os.path.join(HERE, "calendar.json")
CAL_CACHE = os.path.join(HERE, "calendar_cache.json")
SUMMARY = os.path.join(HERE, "paper_news_summary.txt")
CSV_HEAD = ["trade", "stream", "event", "market", "slot", "role", "start_ke", "end_ke", "start_et", "entry_ke", "entry_vs_open_s", "cash_before", "equity_before", "pending_loss", "stake",
            "capped", "result", "pnl", "taker_fee", "maker_rebate", "pnl_incl_rebate", "up_sold", "down_sold", "crossed", "size_ok", "result_mid", "pnl_mid", "winner", "equity_after", "source"]
DAILY_HEAD = ["period_start_ke", "period_end_ke", "trades_closed", "hedged", "miss_lose", "miss_win", "no_fill", "trade_pnl_usd", "news_pnl_usd", "open_pnl_usd", "maker_rebate_usd", "taker_fees_usd", "day_total_usd", "equity_usd", "free_cash_usd", "pending_recovery_usd", "open_trades", "since_start_pct"]
REBATE_HEAD = ["period_start_ke", "period_end_ke", "maker_fills", "shares_sold_at_55c", "fee_equivalent_usd", "maker_rebate_usd", "cumulative_rebate_usd", "taker_sells", "taker_fees_usd", "paid_out_usd", "unpaid_usd"]

# ------------------------------------------------------------------------------------------------ calendar
D = lambda s: date.fromisoformat(s)
BUILTIN = {
    "CPI": ["2026-04-10", "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
            "2027-01-13", "2027-02-11", "2027-03-10", "2027-04-13"],
    "NFP": ["2026-04-03", "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
            "2027-01-08", "2027-02-05", "2027-03-05", "2027-04-02"],
    "PPI": ["2026-03-18", "2026-04-14", "2026-05-13", "2026-06-11", "2026-07-15", "2026-08-13", "2026-09-10", "2026-10-15", "2026-11-13", "2026-12-15",
            "2027-01-14", "2027-02-12", "2027-03-12", "2027-04-14"],
    "FOMC": ["2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
             "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"],
}
HOLIDAYS = ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
            "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"]
REL_TIME = {"CPI": (8, 30), "NFP": (8, 30), "PPI": (8, 30), "FOMC": (14, 0)}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
BLS_PAGES = {"CPI": "https://www.bls.gov/schedule/news_release/cpi.htm", "PPI": "https://www.bls.gov/schedule/news_release/ppi.htm",
             "NFP": "https://www.bls.gov/schedule/news_release/empsit.htm"}
BLS_RELEASE = {"CPI": "https://www.bls.gov/news.release/cpi.nr0.htm", "PPI": "https://www.bls.gov/news.release/ppi.nr0.htm",
               "NFP": "https://www.bls.gov/news.release/empsit.nr0.htm"}
FED_PAGE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def et_epoch(d, h, m=0):
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=ET).timestamp())


def et_date(ts):
    return datetime.fromtimestamp(ts, UTC).astimezone(ET).date()


def stamp(ts):
    """'Wed 10 Dec 14:00 Nairobi (06:00 ET)'"""
    return f"{datetime.fromtimestamp(ts, KE):%a %d %b %H:%M} Nairobi ({datetime.fromtimestamp(ts, UTC).astimezone(ET):%H:%M} ET)"


def hm_ke(ts):
    return f"{datetime.fromtimestamp(ts, KE):%Y-%m-%d %H:%M}"


def hm_et(ts):
    return f"{datetime.fromtimestamp(ts, UTC).astimezone(ET):%Y-%m-%d %H:%M}"


def keep_header(path, head):
    """if a results file written by an older version has other columns, move it aside so the columns never get mixed"""
    try:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            first = open(path, encoding="utf-8").readline().strip()
            if first != ",".join(head):
                old = first.split(",")
                if len(old) < len(head) and head[:len(old)] == old:           # the only change is extra columns at the end: upgrade the file in place
                    rows = list(csv.reader(open(path, encoding="utf-8", newline="")))
                    with open(path, "w", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        w.writerow(head)
                        for r in rows[1:]:
                            w.writerow(r + ["live"] * (len(head) - len(r)))
                else:
                    os.replace(path, path.replace(".csv", f"_old_{int(time.time())}.csv"))
    except Exception:
        pass


def text_of(html):
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t))


DATE_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d)\b", re.I)


def parse_bls(html):
    """release dates (date objects) from a BLS schedule page: every 'Mon. D, YYYY' followed within 60 characters by an 8:30 time"""
    t = text_of(html)
    out = set()
    for m in DATE_RE.finditer(t):
        if re.search(r"\b0?8:30", t[m.end():m.end() + 60]):
            try:
                out.add(date(int(m.group(3)), MONTHS[m.group(1).lower()[:3]], int(m.group(2))))
            except ValueError:
                pass
    return out


def parse_fomc(html):
    """decision days (second day of each meeting) from the Federal Reserve calendar page"""
    t = text_of(html)
    out = set()
    parts = re.split(r"(20\d\d)\s+FOMC\s+Meetings", t)
    for i in range(1, len(parts) - 1, 2):
        year = int(parts[i])
        chunk = parts[i + 1][:2500]
        for m in re.finditer(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*[-–]\s*(?:(January|February|March|April|May|June|July|August|September|October|November|December)\s+)?(\d{1,2})\b", chunk):
            mon = m.group(3) or m.group(1)
            try:
                out.add(date(year, MONTHS[mon.lower()[:3]], int(m.group(4))))
            except ValueError:
                pass
    return out


class Calendar:
    def __init__(self, user_path=CAL_USER, cache_path=CAL_CACHE):
        self.user_path, self.cache_path = user_path, cache_path
        self.lock = threading.Lock()
        self.online = {}                 # kind -> set(dates) last parsed online
        self.load()

    def load(self):
        with self.lock:
            self.user = {}
            try:
                self.user = json.load(open(self.user_path, encoding="utf-8"))
            except Exception:
                pass
            try:
                c = json.load(open(self.cache_path, encoding="utf-8"))
                self.online = {k: {D(x) for x in v} for k, v in c.get("online", {}).items()}
            except Exception:
                pass

    def events(self):
        """sorted list of (date, kind) = built-in + online-confirmed + user additions - user removals"""
        with self.lock:
            ev = {(D(x), k) for k, v in BUILTIN.items() for x in v}
            ev |= {(d, k) for k, v in self.online.items() for d in v if not self.suspect(k, d)}
            ev |= {(D(a["date"]), a["kind"].upper()) for a in self.user.get("add", [])}
            rem = {D(x) for x in self.user.get("remove", [])}
            return sorted(e for e in ev if e[0] not in rem and e[1] in REL_TIME)

    @staticmethod
    def suspect(kind, d):
        """an online FOMC date inside a year the built-in list already covers completely, but not in that list, is a parsing slip (e.g. the next year's meeting read into this year): ignore it"""
        if kind != "FOMC":
            return False
        return d.year in (2026, 2027) and d not in {D(x) for x in BUILTIN["FOMC"]}

    def release_days(self):
        return {d for d, _ in self.events()}

    def holidays(self):
        return {D(x) for x in HOLIDAYS} | {D(x) for x in self.user.get("holidays", [])}

    def last_date(self):
        """the date up to which EVERY kind of release is covered (the earliest of the four last dates)"""
        last = {}
        for d, k in self.events():
            last[k] = max(last.get(k, d), d)
        return min(last.values()) if len(last) == len(REL_TIME) else (min(last.values()) if last else None)

    def refresh(self, fetch, today):
        """fetch(url)->html or None.  Returns a list of alert strings (changes)."""
        msgs, new_online, failed = [], {}, []
        for kind, url in BLS_PAGES.items():
            h = fetch(url)
            ds = parse_bls(h) if h else set()
            if len(ds) >= 3:
                new_online[kind] = ds
            else:
                failed.append(kind)
        h = fetch(FED_PAGE)
        ds = parse_fomc(h) if h else set()
        if len(ds) >= 3:
            new_online["FOMC"] = ds
        else:
            failed.append("FOMC")
        if failed:
            msgs.append("calendar: could not read the online schedule for " + ", ".join(failed) + " (offline or the page layout changed); using the saved dates")
        with self.lock:
            for kind, ds in new_online.items():
                built = {D(x) for x in BUILTIN[kind]}
                added = sorted(d for d in ds if d >= today and d not in built and not self.suspect(kind, d))
                gone = sorted(d for d in built if today <= d <= max(ds) and d not in ds)
                if added:
                    msgs.append(f"ALERT calendar: NEW {kind} date(s) online, now included: " + ", ".join(f"{d:%a %d %b %Y}" for d in added))
                if gone:
                    msgs.append(f"ALERT calendar: {kind} date(s) NOT confirmed online (postponed? check by hand, 'remove' them in calendar.json if cancelled): "
                                + ", ".join(f"{d:%a %d %b %Y}" for d in gone))
            self.online.update(new_online)
            try:
                json.dump({"online": {k: sorted(d.isoformat() for d in v) for k, v in self.online.items()}, "saved": int(time.time())},
                          open(self.cache_path, "w", encoding="utf-8"))
            except Exception:
                pass
        return msgs


# ------------------------------------------------------------------------------------------------ the plan: chains of candles
class Chain:
    def __init__(self, cid, stream, tf, label, slots, nsched, recov):
        self.cid, self.stream, self.tf, self.label = cid, stream, tf, label
        self.slots = slots             # list of (start, end)
        self.nsched, self.recov = nsched, recov


def event_chains(kind, d, recov=True, rtfs=("1h",)):
    h0, (rh, rm) = (12, REL_TIME["FOMC"]) if kind == "FOMC" else (6, REL_TIME[kind])
    label = f"{kind} {d:%d %b %Y}"
    out = []
    hs = [(et_epoch(d, h0 + i), et_epoch(d, h0 + i) + 3600) for i in range(7)]
    out.append(Chain(f"{kind}-{d}-1h", "news", "1h", label, hs, 6, recov and "1h" in rtfs))
    s4 = et_epoch(d, 12 if kind == "FOMC" else 8)
    out.append(Chain(f"{kind}-{d}-4h", "news", "4h", label, [(s4, s4 + 14400), (s4 + 14400, s4 + 28800)], 1, recov and "4h" in rtfs))
    ds = d if kind == "FOMC" else d - timedelta(days=1)
    day = [(et_epoch(ds + timedelta(days=i), 12), et_epoch(ds + timedelta(days=i + 1), 12)) for i in range(2)]
    out.append(Chain(f"{kind}-{d}-1d", "news", "1d", label, day, 1, recov and "1d" in rtfs))
    return out


def open_chain(d):
    s = et_epoch(d, 9)
    return Chain(f"OPEN-{d}", "open", "1h", f"US open {d:%d %b %Y}", [(s, s + 3600)], 1, False)


def plan_chains(cal, d0, d1, open_on=True, recov=True, rtfs=("1h",)):
    """all chains whose first candle starts between day d0 and d1 (dates)"""
    out = []
    rel = cal.release_days()
    for d, kind in cal.events():
        if d0 - timedelta(days=2) <= d <= d1 + timedelta(days=1):
            out += event_chains(kind, d, recov, rtfs)
    if open_on:
        hol = cal.holidays()
        d = d0
        while d <= d1:
            if d.weekday() < 5 and d not in rel and d not in hol:
                out.append(open_chain(d))
            d += timedelta(days=1)
    return out


def first_start(chain):
    return chain.slots[0][0]


# ------------------------------------------------------------------------------------------------ network (real)
class Net:
    def __init__(self):
        import requests
        self.rq = requests
        self.cache = {}

    def jget(self, url, params=None):
        for i in range(3):
            try:
                r = self.rq.get(url, params=params, timeout=15)
                if r.ok:
                    return r.json()
                if r.status_code != 429 and r.status_code < 500:
                    return None                                   # 404 etc: the thing does not exist, no point asking again
            except Exception:
                pass
            time.sleep(1.0 + i)                                   # network hiccup / rate limit: try again
        return None

    @staticmethod
    def slugs(tf, start):
        if tf == "4h":
            return [f"btc-updown-4h-{start}"]
        if tf == "1h":
            et = datetime.fromtimestamp(start, UTC).astimezone(ET)
            h12 = f"{et.hour % 12 or 12}{'am' if et.hour < 12 else 'pm'}"
            mon = et.strftime("%B").lower()
            return [f"bitcoin-up-or-down-{mon}-{et.day}-{et.year}-{h12}-et", f"btc-updown-1h-{start}", f"bitcoin-up-or-down-{mon}-{et.day}-{h12}-et"]
        et = et_date(start + 86400 + 3600)        # older daily markets are named after the day they end (noon ET)
        mon = et.strftime("%B").lower()
        return [f"btc-updown-1d-{start}", f"btc-updown-1d-{start + 86400}", f"bitcoin-up-or-down-on-{mon}-{et.day}-{et.year}", f"bitcoin-up-or-down-on-{mon}-{et.day}"]

    @staticmethod
    def parse(ev):
        for mk in (ev or {}).get("markets", []):
            try:
                toks = mk["clobTokenIds"]
                toks = json.loads(toks) if isinstance(toks, str) else toks
                outs = mk.get("outcomes", '["Up","Down"]')
                outs = json.loads(outs) if isinstance(outs, str) else outs
                names = [o.lower() for o in outs]
                prices = mk.get("outcomePrices")
                prices = json.loads(prices) if isinstance(prices, str) else prices
                winner = None
                if prices:
                    pr = [float(x) for x in prices]
                    if max(pr) >= 0.99:
                        winner = names[pr.index(max(pr))]
                return {"up": toks[names.index("up")], "down": toks[names.index("down")]}, winner
            except Exception:
                continue
        return None, None

    def event(self, tf, start):
        key = (tf, start)
        order = ([self.cache[key]] if key in self.cache else []) + self.slugs(tf, start)
        length = {"1h": 3600, "4h": 14400, "1d": 86400}[tf]
        for sl in order:
            ev = self.jget(f"{GAMMA}/events/slug/{sl}")
            if ev and self.right_time(ev, start + length):
                self.cache[key] = sl
                return ev
        return None

    @staticmethod
    def right_time(ev, end):
        """a market name can repeat from one year to the next (e.g. ...-november-18-9am-et): accept the event only if its end date is the end of THIS candle (within 3 h); no date given = accept"""
        try:
            ds = [ev.get("endDate")] + [m.get("endDate") for m in ev.get("markets", [])]
            ds = [x for x in ds if x]
            if not ds:
                return True
            got = [datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp() for x in ds]
            return any(abs(g - end) <= 3 * 3600 for g in got)
        except Exception:
            return True

    def load_market(self, tf, start):
        return self.parse(self.event(tf, start))[0]

    def winner(self, tf, start):
        return self.parse(self.event(tf, start))[1]

    def trades(self, tf, start):
        """every taker trade of the market (real executed trades): list of (timestamp, 'up'|'down', price, shares), or None if the market/trades cannot be read"""
        ev = self.event(tf, start)
        tok, _ = self.parse(ev)
        cond = None
        for mk in (ev or {}).get("markets", []):
            if mk.get("conditionId"):
                cond = mk["conditionId"]
                break
        if not (tok and cond):
            return None
        rev = {str(tok["up"]): "up", str(tok["down"]): "down"}
        rows, seen, cursor, pages = [], set(), None, 0
        while pages < 300:
            params = {"condition": cond, "limit": 1000, "taker_only": "true"}
            if cursor:
                params["cursor"] = cursor
            d = self.jget(f"{DATA}/v2/trades", params)
            if not isinstance(d, dict) or not isinstance(d.get("data"), list):
                return rows if rows else None
            for r in d["data"]:
                try:
                    side = rev.get(str(r.get("token_id", r.get("asset"))))
                    if side is None:
                        o = str(r.get("outcome", "")).lower()
                        side = o if o in ("up", "down") else None
                    if side is None:
                        continue
                    key = (r.get("transaction_hash", r.get("transactionHash")), side, r.get("price"), r.get("size"), r.get("timestamp"), r.get("side"))
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append((int(r["timestamp"]), side, float(r["price"]), float(r["size"])))
                except Exception:
                    continue
            pages += 1
            cursor = (d.get("pagination") or {}).get("next_cursor")
            if not cursor or not d["data"]:
                break
        return rows

    @staticmethod
    def parse_book(d):
        bids = sorted(((float(x["price"]), float(x["size"])) for x in d.get("bids", [])), reverse=True)
        asks = sorted((float(x["price"]), float(x["size"])) for x in d.get("asks", []))
        return {"bids": bids, "asks": asks}

    def books(self, tokens):
        out = {}
        tokens = list(tokens)
        if not tokens:
            return out
        try:
            r = self.rq.post(f"{CLOB}/books", json=[{"token_id": t} for t in tokens], timeout=15)
            if r.ok:
                for d in r.json():
                    out[str(d.get("asset_id"))] = self.parse_book(d)
        except Exception:
            pass
        for t in tokens:
            if t not in out:
                d = self.jget(f"{CLOB}/book", {"token_id": t})
                if d:
                    out[t] = self.parse_book(d)
        return out

    def fetch_page(self, url):
        try:
            r = self.rq.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (paper-news-listener)"})
            return r.text if r.ok else None
        except Exception:
            return None


# ------------------------------------------------------------------------------------------------ the engine
def best(book):
    bb = book["bids"][0] if book and book["bids"] else (None, None)
    ba = book["asks"][0] if book and book["asks"] else (None, None)
    return bb[0], bb[1], ba[0], ba[1]


def legs_pnl(pos, var, winner):
    """(pnl, result) of variant `var` ('bid' or 'mid') of a position, or (None, None) if the winner is needed and unknown"""
    N = pos["stake"]
    legs = pos["v"][var]
    sold = [k for k, l in legs.items() if l]
    proceeds = sum(N * l["p"] - l["fee"] for l in legs.values() if l)
    if len(sold) == 2:
        return proceeds - N, "hedged"
    if len(sold) == 0:
        return 0.0, "no_fill"
    if not winner:
        return None, None
    held = [k for k in ("up", "down") if k not in sold][0]
    payoff = N if winner == held else 0.0
    return proceeds + payoff - N, ("miss_win" if payoff else "miss_lose")


class Engine:
    def __init__(self, cfg, net, cal, state=None, log=None, state_path=STATE_JSON, csv_path=TRADES_CSV):
        self.cfg, self.net, self.cal = cfg, net, cal
        self.log = log or (lambda m: print(m))
        self.state_path, self.csv_path = state_path, csv_path
        c = cfg["capital"]
        self.st = state or {"cash": c, "locked": 0.0, "peak": c, "chains": {}, "slots": {}, "slotmap": {}, "alerts": [], "trades": 0, "start_capital": c}
        for k, v in (("rebates", []), ("takerfees", []), ("closed", []), ("eq_prev", None), ("rebate_unpaid", 0.0), ("rebate_paid", 0.0), ("next_cut", None), ("period_start", None), ("first_start", None), ("wake_at", None), ("last_seen", None)):
            self.st.setdefault(k, v)
        d = os.path.dirname(os.path.abspath(csv_path))
        self.reb_csv, self.reb_log = os.path.join(d, "paper_news_rebates.csv"), os.path.join(d, "paper_news_rebates.log")
        self.day_csv, self.day_log = os.path.join(d, "paper_news_daily.csv"), os.path.join(d, "paper_news_daily.log")
        self.notify = None
        self.books = {}
        self.dirty = True

    # ---- persistence
    def save(self):
        tmp = self.state_path + ".tmp"
        json.dump(self.st, open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, self.state_path)
        self.dirty = False

    @property
    def equity(self):
        return self.st["cash"] + self.st["locked"]

    # ---- plan
    def ensure(self, now):
        if self.st.get("first_start") is None:             # the moment this paper account really began (candles before it are never back-filled)
            ent = [sl["pos"]["entry_ts"] for sl in self.st["slots"].values() if sl.get("pos")]
            self.st["first_start"] = int(min(ent)) if ent else int(now)
            self.dirty = True
        d0 = et_date(now - (self.cfg.get("bf_days", 0) * 86400 if self.cfg.get("backfill") else 0)) - timedelta(days=1)
        d1 = et_date(now) + timedelta(days=2)
        for ch in plan_chains(self.cal, d0, d1, self.cfg["open_on"], self.cfg["recovery"], self.cfg["recov_tfs"]):
            if ch.cid in self.st["chains"]:
                continue
            ids, claimed = [], 0
            for i, (s, e) in enumerate(ch.slots):
                sid = f"{ch.tf}|{s}"
                if sid in self.st["slotmap"]:
                    continue                                   # another chain already owns this candle
                self.st["slotmap"][sid] = ch.cid
                ids.append(sid)
                self.st["slots"][sid] = {"chain": ch.cid, "stream": ch.stream, "tf": ch.tf, "start": s, "end": e, "label": ch.label, "sched": i < ch.nsched,
                                         "status": "future", "pos": None, "tok": None, "next_try": 0, "why": ""}
            if ids:
                self.st["chains"][ch.cid] = {"stream": ch.stream, "tf": ch.tf, "label": ch.label, "slots": ids, "pend": 0.0, "recov": ch.recov}
                self.dirty = True

    def prev_slot(self, s):
        ch = self.st["chains"][s["chain"]]
        i = ch["slots"].index(f"{s['tf']}|{s['start']}")
        return self.st["slots"][ch["slots"][i - 1]] if i > 0 else None

    # ---- one tick
    def early_ok(self, s, now):
        """the candle before has just completed its hedge (both legs sold, closed) and this candle is a normal scheduled one of the same chain: its orders can go in NOW instead of 5 minutes before the open"""
        if not self.cfg.get("early", True) or s["status"] != "future" or not s["sched"] or now >= s["start"]:
            return False
        p = self.prev_slot(s)
        return bool(p is not None and p["end"] == s["start"] and p["status"] == "done" and p.get("pos") and p["pos"].get("res") == "hedged" and not p["pos"].get("backfill"))

    def reconcile(self, now, since):
        """the bot was not watching (asleep, or off): re-judge the open trades from Polymarket's real trades. A resting 55c sell fills when somebody buys that side at 55c or more."""
        cfg = self.cfg
        for sid, s in sorted(self.st["slots"].items(), key=lambda kv: kv[1]["start"]):
            pos = s.get("pos")
            if s["status"] != "open" or not pos or pos.get("logged") or pos.get("backfill"):
                continue
            unsold = [l for l in ("up", "down") if pos["v"]["bid"][l] is None]
            if not unsold:
                continue
            tr = self.net.trades(s["tf"], s["start"])
            if not tr:
                continue
            lo, hi = max(pos["entry_ts"], since), min(now, s["end"])
            N = pos["stake"]
            ps = self.st.get("period_start")
            for leg in unsold:
                ok = [(ts, sz) for ts, sd, px, sz in tr if sd == leg and lo <= ts < hi and px >= TARGET - 1e-9]
                if not ok:
                    continue
                ts0, shares = min(o[0] for o in ok), sum(o[1] for o in ok)
                fe = N * FEE * TARGET * (1 - TARGET)
                rb = cfg["rebate"] * fe
                pos["v"]["bid"][leg] = {"p": TARGET, "ts": int(ts0), "fee": 0.0, "crossed": False, "size": round(shares, 2), "rebate": round(rb, 5)}
                if pos["v"]["mid"][leg] is None:
                    pos["v"]["mid"][leg] = {"p": TARGET, "ts": int(ts0), "fee": 0.0, "crossed": False, "size": None}
                if shares < N:
                    pos["size_ok"] = False
                self.st["rebates"].append([int(ts0 if (ps is not None and ts0 >= ps) else now), pos["n"], leg, N, round(fe, 5), round(rb, 5)])
                self.log(f"   #{pos['n']} {leg.upper()} leg sold at 0.55 while the bot was asleep (real trades) {stamp(ts0)}")
                self.ping(f"#{pos['n']} {leg.upper()} leg sold at 0.55 (found after waking) {stamp(ts0)}")
                self.dirty = True
            if all(pos["v"]["bid"].values()) and s["status"] == "open":
                self.maybe_close_early(s, now)

    def next_wake(self, now):
        """rest=1: None while the bot must stay awake, else the time to wake up (`wake` seconds, default 15 min, before the next candle that needs it).
        Awake: a missed candle is waiting to be rebuilt, an hourly trade is running (or opens within `wake`), or an order can go in now."""
        cfg = self.cfg
        if not cfg.get("rest"):
            return None
        slots = self.st["slots"]
        wake = cfg.get("wake", 900)
        nxt = None
        for s in slots.values():
            if s["status"] == "missed":
                return None
            if s["status"] == "open" and s["tf"] == "1h" and s["pos"] and not s["pos"].get("logged"):
                if s["start"] - wake <= now:
                    return None
                nxt = s["start"] - wake if nxt is None else min(nxt, s["start"] - wake)
            if s["status"] == "future":
                owed = s["sched"] or self.pend_for(self.st["chains"][s["chain"]], f"{s['tf']}|{s['start']}") > 1e-9      # a recovery candle after a loss is owed too
                if owed and (s["start"] - cfg["lead"] <= now or self.early_ok(s, now)):
                    return None
                if owed and s["end"] > now:
                    t0 = s["start"] - wake
                    nxt = t0 if nxt is None else min(nxt, t0)
        for a, b in alert_windows(self.cal, now):
            if a <= now < b:
                return None                                           # a calendar alert is due: stay awake
            if a > now:
                nxt = a if nxt is None else min(nxt, a)
        if nxt is None or nxt - now < wake + 600:
            return None                                           # the next thing is close: just stay in the run and wait (no start-up risk)
        return int(nxt)

    def step(self, now):
        self.ensure(now)
        ls = self.st.get("last_seen")
        if ls and now - ls > 90:
            self.reconcile(now, ls)
        self.st["last_seen"] = int(now)
        slots = self.st["slots"]
        order = sorted((s["start"], sid) for sid, s in slots.items())
        # which tokens do we need books for?
        need = set()
        for _, sid in order:
            s = slots[sid]
            if s["status"] == "open" and now < s["end"]:
                need |= set(s["pos"]["tok"].values())
            elif s["status"] == "future" and (s["start"] - self.cfg["lead"] - 30 <= now < s["start"] + self.cfg["maxlate"] or self.early_ok(s, now)):
                if s["tok"] is None and now >= s["next_try"]:
                    s["next_try"] = now + 8
                    s["tok"] = self.net.load_market(s["tf"], s["start"])
                    self.dirty = True
                if s["tok"]:
                    need |= set(s["tok"].values())
        self.books = self.net.books(need) if need else {}
        late_future = any(x["status"] == "missed" or (x["status"] == "future" and now > x["start"] + self.cfg["maxlate"]) for x in slots.values())
        if not self.cfg.get("backfill") or not late_future:
            self.settle_due(now, order)                              # ended trades free their cash before new orders are sized
        for _, sid in order:
            s = slots[sid]
            if s["status"] == "future" and (s["start"] - self.cfg["lead"] <= now or self.early_ok(s, now)):
                self.try_enter(sid, s, now)
        for _, sid in order:
            s = slots[sid]
            if s["pos"] is not None and s["status"] == "open" and now < s["end"]:
                self.update_fills(s["pos"], now, first=False)
                self.maybe_close_early(s, now)
        self.backfill(now)                                          # rebuild missed candles (in time order) before today's settlements, so cash is as it would have been
        self.settle_due(now, order)
        self.rebate_report(now)
        if self.dirty:
            self.save()

    def settle_due(self, now, order):
        slots = self.st["slots"]
        miss = [x["start"] for x in slots.values() if x["status"] == "missed"] if self.cfg.get("backfill") else []
        for _, sid in order:
            s = slots[sid]
            if s["pos"] is not None and not s["pos"].get("logged") and now >= s["end"]:
                if miss and not s["pos"].get("backfill") and min(miss) - self.cfg["lead"] < s["end"]:
                    continue                                         # candles still to be rebuilt entered before this trade ended: settle it in order, after them
                self.settle(s, now)

    @staticmethod
    def pend_for(ch, sid):
        return ch["pend"] if ch.get("pend_for") == sid else 0.0

    def why_wait(self, sid, now, msg):
        """say (at most once a minute) why a candle that is due has not been entered yet"""
        w = self.__dict__.setdefault("_wl", {})
        if now - w.get(sid, 0) >= 60:
            w[sid] = now
            self.log("WAITING " + msg)

    def ping(self, msg):
        """per-trade phone alert (orders placed, leg sold, trade closed); never raises"""
        if self.notify and self.cfg.get("tradealerts", True):
            try:
                self.notify(msg)
            except Exception:
                pass

    def mark_missed(self, s, why, now, quiet=False):
        """a candle the bot could not trade live: with back-fill on it is rebuilt later from the real trades (as if the orders had been placed), otherwise skipped"""
        cfg = self.cfg
        if cfg.get("backfill") and s["start"] >= (self.st.get("first_start") or 0) and now - s["start"] <= cfg.get("bf_days", 0) * 86400:
            s["status"], s["why"] = "missed", why
            self.dirty = True
            if not quiet:
                self.log(f"MISSED {s['tf']} {s['label']} candle {stamp(s['start'])}: {why} -> will be back-filled from the real trades once the candle is over")
            return
        return self.skip(s, why, quiet=quiet)

    def skip(self, s, why, quiet=False):
        s["status"], s["why"] = "skipped", why
        ch = self.st["chains"].get(s["chain"])
        if ch and ch.get("pend_for") == f"{s['tf']}|{s['start']}":
            ch["pend"], ch["pend_for"] = 0.0, None            # the recovery candle could not be traded: the loss is taken
        self.dirty = True
        if not quiet:
            self.log(f"skip {s['tf']} {s['label']} candle {stamp(s['start'])}: {why}")

    def try_enter(self, sid, s, now):
        """place the pair + the two 55c sell limits `lead` seconds before the candle opens (or as soon as the previous result allows)"""
        cfg = self.cfg
        ch = self.st["chains"][s["chain"]]
        p = self.prev_slot(s)
        if now >= s["end"]:
            return self.mark_missed(s, "candle already over", now, quiet=True)
        if p is not None and p["status"] == "missed" and cfg.get("backfill") and now - p["end"] < 3 * 3600:
            return                                                # the candle before is being rebuilt from the real trades: its result sets this stake
        prev_open = p is not None and p["status"] == "open"
        waited = now - s["start"]
        if not s["sched"]:
            # recovery candle: only after a loss, and the previous result decides whether there is one
            if prev_open:
                if waited < cfg["recwait"]:
                    return
                return self.skip(s, "previous result unknown", quiet=True)
            if not ch["recov"] or self.pend_for(ch, sid) <= 1e-9:
                return self.skip(s, "no recovery needed", quiet=True)
        elif ch["recov"] and prev_open and sum(1 for l in p["pos"]["v"]["bid"].values() if l) == 1 and waited < cfg["recwait"]:
            return                                                # one leg of the previous candle is sold: it may become a loss that sets this stake
        if waited > cfg["maxlate"] or now >= s["end"] - 30:
            return self.mark_missed(s, "missed: the candle was already running (bot was off, or the market was not found in time)", now)
        tok = s["tok"]
        if not tok:
            self.why_wait(sid, now, f"{s['tf']} {s['label']}: the market cannot be found on Polymarket yet (Gamma API gave nothing)")
            return
        bk = {k: self.books.get(t) for k, t in tok.items()}
        if not (bk["up"] and bk["down"]):
            self.why_wait(sid, now, f"{s['tf']} {s['label']}: market found but the order books cannot be read (CLOB API gave nothing for Up/Down)")
            return
        stake, capped, pend, base, basename, free = self.size_stake(ch, sid)
        frac, cap = cfg["stake"], cfg["cap"]
        if stake < cfg["minstake"]:
            return self.skip(s, f"stake ${stake:.2f} below the minimum (free cash ${free:.2f}; the rest is locked in open trades)")
        eq = self.equity
        pos = {"stake": stake, "entry_ts": now, "late": int(waited), "pend0": round(pend, 4), "capped": capped, "eq0": round(eq, 4), "cash0": round(free, 4), "tok": tok,
               "v": {"bid": {"up": None, "down": None}, "mid": {"up": None, "down": None}}, "size_ok": True, "logged": False, "winner": None, "next_w": 0}
        self.st["cash"] -= stake
        self.st["locked"] += stake
        s["pos"], s["status"] = pos, "open"
        self.st["trades"] += 1
        pos["n"] = self.st["trades"]
        self.dirty = True
        role = "scheduled" if s["sched"] else "recovery"
        when = (f"{-pos['late']}s before the open" if pos["late"] < -20 else f"{pos['late']}s after the open" if pos["late"] > 20 else "at the open")
        self.log(f"ORDERS #{pos['n']} {s['tf']} {s['label']} ({role}) candle {stamp(s['start'])}: SPLIT ${stake:.2f} into {stake:.2f} Up + {stake:.2f} Down, SELL limits at 55c on both ({when}); stake "
                 + (f"= 10x pending loss ${pend:.2f}" + (" (capped at {:.0%} of {})".format(cap, basename) if capped else "") if pend / 0.10 > frac * base + 1e-9
                    else f"= {frac:.0%} of {basename} ${base:.2f}" + (f" (pending loss ${pend:.2f} is small: normal stake)" if pend > 1e-9 else "")
                    + (f", cut to the free cash ${free:.2f}" if stake > free + 0.005 else "")))
        self.ping(f"TRADE #{pos['n']} {s['tf']} {s['label']} ({role}): orders in, stake ${stake:.2f}" + (f" (10x pending loss ${pend:.2f})" if pend > 1e-9 else "")
                  + f"; candle {stamp(s['start'])}")
        self.update_fills(pos, now, first=True)
        self.maybe_close_early(s, now)

    def size_stake(self, ch, sid):
        """the stake rule (shared by live trading and back-fill): 20% of FREE cash (or of total capital), 10x the pending loss on the candle right after a loss, capped, whole cents"""
        cfg = self.cfg
        free = self.st["cash"]                                    # money not locked in open trades
        base = free if cfg["base"] == "free" else self.equity     # stake = a share of the FREE cash (default) or of the TOTAL capital (base=total); never more than the free cash
        basename = "free cash" if cfg["base"] == "free" else "total capital"
        frac, cap = cfg["stake"], cfg["cap"]
        pend = self.pend_for(ch, sid) if ch["recov"] else 0.0       # a loss is chased on the NEXT candle only
        stake, capped = frac * base, False
        if pend > 1e-9:
            want = pend / 0.10
            stake = max(stake, want)
            if stake > cap * base:
                stake, capped = cap * base, True
        stake = math.floor(min(stake, free) * 100 + 1e-9) / 100        # whole cents, never more than the free cash
        return stake, capped, pend, base, basename, free

    # ---- back-fill: candles the bot could not trade live (laptop off) are rebuilt from Polymarket's real trades, in time order, so cash and recovery sizing follow as if they had been traded
    def backfill(self, now):
        cfg = self.cfg
        if not cfg.get("backfill"):
            return
        slots = self.st["slots"]
        fs = self.st.get("first_start") or 0
        for s in slots.values():                                   # candles an older run skipped for being missed
            if s["status"] == "skipped" and (s["why"].startswith("candle already over") or s["why"].startswith("missed:")) and s["start"] >= fs and now - s["start"] <= cfg["bf_days"] * 86400 and not s.get("bf_seen"):
                s["status"] = "missed"
                self.dirty = True
            s.setdefault("bf_seen", True) if s["status"] != "missed" else None
        todo = sorted((s["start"], s["tf"] == "1h", sid) for sid, s in slots.items() if s["status"] == "missed" and now >= s["end"] + cfg["bf_delay"])
        if not todo:
            return
        heap, done, seq = [], [], 0
        for _, _, sid in todo:
            if len(done) >= 6:
                break                                                # a few candles per tick: the network calls take time
            s = slots[sid]
            ch = self.st["chains"][s["chain"]]
            r = self.backfill_one(sid, s, ch, now, heap, seq)
            seq += 1
            if r == "wait":
                break                                                # data not ready: retry later, keeping time order
            if r == "done":
                done.append(sid)
        self.flush_backfill(heap, now)
        if done and self.notify:
            try:
                pn = sum(slots[x]["pos"]["pnl"] for x in done if slots[x].get("pos") and "pnl" in slots[x]["pos"])
                self.notify(f"BACK-FILL: {len(done)} candles missed while the bot was off were rebuilt from the real trades: PnL {pn:+.2f}; equity ${self.equity:.2f}")
            except Exception:
                pass

    def flush_backfill(self, heap, upto):
        while heap and heap[0][0] <= upto:
            ct, _, sid, pnl, res, acct = heapq.heappop(heap)
            s = self.st["slots"][sid]
            pos = s["pos"]
            self.close(s, pnl, res, acct)
            pm, rm = legs_pnl(pos, "mid", pos["winner"])
            self.write_row(s, pm, rm)
            pos["logged"] = True
            self.dirty = True

    def backfill_one(self, sid, s, ch, now, heap, seq):
        cfg = self.cfg
        prev = self.prev_slot(s)
        if prev is not None and prev["status"] == "open":
            return "wait"                                          # the candle before is still being settled live
        late = bool(prev is not None and ch["recov"] and prev.get("pos") and prev["pos"].get("res") in ("miss_lose", "miss_win"))
        et = s["start"] + (60 if late else -cfg["lead"])           # when the orders would have gone in (same rule as live)
        self.flush_backfill(heap, et)                              # backfilled candles that had closed by then free their cash first
        for o in sorted((x for x in self.st["slots"].values() if x["status"] == "open" and x["pos"] and not x["pos"].get("backfill") and not x["pos"].get("logged") and x["end"] <= et), key=lambda x: x["end"]):
            self.settle(o, now)                                    # live trades that ended before this entry free their cash first (time order)
            if o["status"] == "open":
                return "wait"
        if not s["sched"]:
            if not ch["recov"] or self.pend_for(ch, sid) <= 1e-9:
                return self.skip(s, "no recovery needed", quiet=True) or "skipped"
        age = now - s["end"]
        tr = self.net.trades(s["tf"], s["start"])
        if not tr:
            if age > 2 * 3600:
                self.skip(s, "back-fill: no trade data could be read for this candle")
                return "skipped"
            return "wait"
        mx = {sd: max([px for ts, s2, px, sz in tr if s2 == sd and et <= ts < s["end"]] or [0]) for sd in ("up", "down")}
        legs = {}
        shares = {}
        for side in ("up", "down"):
            ok = [(ts, px, sz) for ts, sd, px, sz in tr if sd == side and et <= ts < s["end"] and px >= TARGET - 1e-9]
            legs[side] = min(ts for ts, _, _ in ok) if ok else None
            shares[side] = sum(sz for _, _, sz in ok)
        winner = None
        if (legs["up"] is None) != (legs["down"] is None):          # exactly one leg sold: the winner decides
            winner = self.net.winner(s["tf"], s["start"])
            if not winner:
                if age > 6 * 3600:
                    self.skip(s, "back-fill: the result of the market is not known")
                    return "skipped"
                return "wait"
        stake, capped, pend, base, basename, free = self.size_stake(ch, sid)
        if stake < cfg["minstake"]:
            self.skip(s, f"back-fill: stake ${stake:.2f} below the minimum (free cash ${free:.2f})")
            return "skipped"
        eq = self.equity
        pos = {"stake": stake, "entry_ts": et, "late": int(et - s["start"]), "pend0": round(pend, 4), "capped": capped, "eq0": round(eq, 4), "cash0": round(free, 4), "tok": {},
               "v": {"bid": {"up": None, "down": None}, "mid": {"up": None, "down": None}}, "size_ok": True, "logged": False, "winner": winner, "next_w": 0, "backfill": True}
        self.st["cash"] -= stake
        self.st["locked"] += stake
        s["pos"], s["status"] = pos, "open"
        self.st["trades"] += 1
        pos["n"] = self.st["trades"]
        ps = self.st.get("period_start")
        for leg in ("up", "down"):                                   # a resting 55c sell fills when somebody buys that side at 55c or more
            if legs[leg] is None:
                continue
            fe = stake * FEE * TARGET * (1 - TARGET)
            rb = cfg["rebate"] * fe
            pos["v"]["bid"][leg] = {"p": TARGET, "ts": legs[leg], "fee": 0.0, "crossed": False, "size": round(shares[leg], 2), "rebate": round(rb, 5)}
            pos["v"]["mid"][leg] = {"p": TARGET, "ts": legs[leg], "fee": 0.0, "crossed": False, "size": None}
            if shares[leg] < stake:
                pos["size_ok"] = False
            self.st["rebates"].append([int(legs[leg] if (ps is not None and legs[leg] >= ps) else now), pos["n"], leg, stake, round(fe, 5), round(rb, 5)])
        pnl, res = legs_pnl(pos, "bid", winner)
        ct = max(legs["up"], legs["down"]) if (legs["up"] is not None and legs["down"] is not None) else s["end"]
        acct = int(ct if (ps is not None and ct >= ps) else now)
        role = "scheduled" if s["sched"] else "recovery"
        self.log(f"BACKFILL #{pos['n']} {s['tf']} {s['label']} ({role}) candle {stamp(s['start'])}: stake ${stake:.2f}" + (f" (10x pending loss ${pend:.2f})" if pend > 1e-9 else f" ({cfg['stake']:.0%} of {basename})")
                 + f"; read {len(tr)} real trades (first {min(x[0] for x in tr) - s['start']:+d}s, last {max(x[0] for x in tr) - s['start']:+d}s vs the open), highest price after the order time: Up {mx['up']:.2f}, Down {mx['down']:.2f}; Up reached 55c {'at ' + stamp(legs['up']) if legs['up'] else 'never'}, Down {'at ' + stamp(legs['down']) if legs['down'] else 'never'} -> {res.upper()}")
        heapq.heappush(heap, (ct, seq, sid, pnl, res, acct))
        self.dirty = True
        return "done"

    def update_fills(self, pos, now, first):
        N = pos["stake"]
        for leg in ("up", "down"):
            b = self.books.get(pos["tok"][leg])
            if not b:
                continue
            bb, bbs, ba, bas = best(b)
            lg = pos["v"]["bid"]
            if lg[leg] is None and bb is not None and bb >= TARGET - 1e-9:
                p = bb if first else TARGET
                fe = N * FEE * p * (1 - p)                          # fee equivalent  N x 0.07 x p x (1-p)
                fee = fe if first else 0.0                          # only a market sale (crossing the book at once) pays it
                rb = 0.0 if first else self.cfg["rebate"] * fe      # a resting limit order that is filled earns the maker rebate
                lg[leg] = {"p": round(p, 4), "ts": int(now), "fee": round(fee, 5), "crossed": bool(first), "size": bbs, "rebate": round(rb, 5)}
                if bbs is not None and bbs < N:
                    pos["size_ok"] = False
                if first:
                    self.st["takerfees"].append([int(now), pos["n"], leg, N, round(p, 4), round(fee, 5)])
                else:
                    self.st["rebates"].append([int(now), pos["n"], leg, N, round(fe, 5), round(rb, 5)])
                self.log(f"   #{pos['n']} {leg.upper()} leg sold at {p:.2f} " + (f"AT ONCE as taker (fee ${fee:.3f})" if first else f"(55c limit, maker, rebate ${rb:.3f})") + f" {stamp(now)}")
                self.dirty = True
                self.ping(f"#{pos['n']} {leg.upper()} leg sold at {p:.2f} ({'taker' if first else 'maker'}) {stamp(now)}")
            lm = pos["v"]["mid"]
            if lm[leg] is None and bb is not None and ba is not None and (bb + ba) / 2 >= TARGET - 1e-9:
                lm[leg] = {"p": TARGET, "ts": int(now), "fee": 0.0, "crossed": False, "size": None}
                self.dirty = True

    def maybe_close_early(self, s, now):
        pos = s["pos"]
        if s["status"] == "open" and all(pos["v"]["bid"].values()):
            pnl, res = legs_pnl(pos, "bid", None)
            self.close(s, pnl, res, now)
            if all(pos["v"]["mid"].values()):                       # hedged under both rules: nothing left to wait for, so write the row now (the bot may sleep before the candle ends)
                pm, rm = legs_pnl(pos, "mid", None)
                self.write_row(s, pm, rm)
                pos["logged"] = True
                self.dirty = True

    def close(self, s, pnl, res, now):
        pos = s["pos"]
        self.st["cash"] += pos["stake"] + pnl
        self.st["locked"] -= pos["stake"]
        if abs(self.st["locked"]) < 1e-9:
            self.st["locked"] = 0.0
        ch = self.st["chains"][s["chain"]]
        if ch["recov"]:
            # recovery lasts ONE candle: a loss on an ordinary candle sets the pending amount for the very next candle;
            # whatever that recovery candle does not win back (or loses) is taken as a realised loss, no further chasing
            if pos["pend0"] > 1e-9:
                ch["pend"], ch["pend_for"] = 0.0, None
            elif pnl < -1e-9:
                sl = ch["slots"]
                i = sl.index(f"{s['tf']}|{s['start']}")
                nxt = sl[i + 1] if i + 1 < len(sl) else None
                if nxt is not None and self.st["slots"][nxt]["status"] not in ("future", "missed"):
                    nxt = None                                  # the next candle is already running/over: nothing to chase
                ch["pend"], ch["pend_for"] = (-pnl, nxt) if nxt else (0.0, None)
            else:
                ch["pend"], ch["pend_for"] = 0.0, None
        self.st["peak"] = max(self.st["peak"], self.equity)
        s["status"] = "done"
        pos["res"], pos["pnl"], pos["eq1"] = res, round(pnl, 4), round(self.equity, 4)
        self.st["closed"].append([int(now), pos["n"], s["stream"], s["tf"], res, round(pnl, 4), 1 if pos.get("backfill") else 0])
        self.dirty = True
        if not pos.get("backfill"):
            self.ping(f"RESULT #{pos['n']} {s['tf']} {s['label']}: {res.upper()} {pnl:+.2f}; equity ${self.equity:.2f}"
                      + (f"; recovery stake next candle ~${ch['pend'] / 0.10:.0f}" if ch["recov"] and ch["pend"] > 0 else ""))
        self.log(f"CLOSE #{pos['n']} {s['tf']} {s['label']}: {res.upper()} {pnl:+.2f} -> free cash ${self.st['cash']:.2f}, equity ${self.equity:.2f}"
                 + (f"  | pending loss on this chain ${ch['pend']:.2f}" if ch["recov"] and ch["pend"] > 0 else ""))

    def settle(self, s, now):
        pos = s["pos"]
        # at the end of the candle: nothing sold -> no_fill (pnl 0).  One leg sold -> need the winner.
        need = any(sum(1 for l in pos["v"][v].values() if l) == 1 for v in ("bid", "mid"))
        if need and not pos["winner"]:
            if now >= pos["next_w"]:
                pos["next_w"] = now + 10
                w = self.net.winner(s["tf"], s["start"])
                if w:
                    pos["winner"] = w
                    self.dirty = True
            if not pos["winner"]:
                if now - s["end"] > 5400:
                    self.log(f"gave up waiting for the result of {s['tf']} {s['label']}; trade closed at its cost")
                    if s["status"] == "open":
                        self.close(s, 0.0, "void", now)
                    pos["logged"] = True
                    self.dirty = True
                return
        if s["status"] == "open":
            pnl, res = legs_pnl(pos, "bid", pos["winner"])
            self.close(s, pnl, res, now)
        pm, rm = legs_pnl(pos, "mid", pos["winner"])
        self.write_row(s, pm, rm)
        pos["logged"] = True
        self.dirty = True

    def write_row(self, s, pm, rm):
        pos = s["pos"]
        v = pos["v"]["bid"]
        keep_header(self.csv_path, CSV_HEAD)
        new = not os.path.exists(self.csv_path)
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(CSV_HEAD)
            tf_ = round(sum(l["fee"] for l in v.values() if l), 5)
            rb_ = round(sum(l.get("rebate", 0.0) for l in v.values() if l), 5)
            w.writerow([pos["n"], s["stream"], s["label"], s["tf"], hm_et(s["start"]), "scheduled" if s["sched"] else "recovery", hm_ke(s["start"]), hm_ke(s["end"]),
                        hm_et(s["start"]), hm_ke(pos["entry_ts"]), pos["late"], pos.get("cash0", pos["eq0"]), pos["eq0"], pos["pend0"], pos["stake"], int(pos["capped"]), pos["res"], pos["pnl"],
                        tf_, rb_, round(pos["pnl"] + rb_, 4),
                        v["up"]["p"] if v["up"] else "", v["down"]["p"] if v["down"] else "", int(any(l and l["crossed"] for l in v.values())), int(pos["size_ok"]),
                        rm or "", round(pm, 4) if pm is not None else "", pos["winner"] or "", pos["eq1"], "backfill" if pos.get("backfill") else "live"])

    # ---- the daily maker-rebate report (every 24 hours at rebate_hour Nairobi time) and the payout
    def next_cut_after(self, now):
        d = datetime.fromtimestamp(now, KE).replace(hour=self.cfg["rebate_hour"], minute=0, second=0, microsecond=0)
        if d.timestamp() <= now:
            d += timedelta(days=1)
        return int(d.timestamp())

    def rebate_report(self, now):
        st = self.st
        if st["next_cut"] is None:
            st["next_cut"], st["period_start"] = self.next_cut_after(now), int(now)
            self.dirty = True
            return
        while now >= st["next_cut"]:
            a, b = st["period_start"], st["next_cut"]
            rows = [r for r in st["rebates"] if a <= r[0] < b]
            tks = [r for r in st["takerfees"] if a <= r[0] < b]
            shares = sum(r[3] for r in rows)
            fe = sum(r[4] for r in rows)
            rb = sum(r[5] for r in rows)
            tfee = sum(r[5] for r in tks)
            st["rebate_unpaid"] += rb
            paid = 0.0
            if st["rebate_unpaid"] >= 1.0:                      # Polymarket pays once the accrued rebate reaches $1
                paid = round(st["rebate_unpaid"], 5)
                st["cash"] += paid
                st["rebate_paid"] += paid
                st["rebate_unpaid"] = 0.0
            cum = sum(r[5] for r in st["rebates"] if r[0] < b)
            line = (f"24h to {hm_ke(b)} Nairobi (from {hm_ke(a)}): MAKER REBATE EARNED ${rb:.4f} on {len(rows)} maker fills ({shares:.2f} shares sold at 55c, fee equivalent ${fe:.4f}); "
                    f"cumulative ${cum:.4f}; paid out ${paid:.2f}, unpaid balance ${st['rebate_unpaid']:.4f}; taker sells {len(tks)} with fees ${tfee:.4f}")
            self.log("REBATE REPORT " + line)
            try:
                open(self.reb_log, "a", encoding="utf-8").write(f"{datetime.now(KE):%Y-%m-%d %H:%M:%S} KE | {line}\n")
                keep_header(self.reb_csv, REBATE_HEAD)
                new = not os.path.exists(self.reb_csv)
                with open(self.reb_csv, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(REBATE_HEAD)
                    w.writerow([hm_ke(a), hm_ke(b), len(rows), round(shares, 2), round(fe, 5), round(rb, 5), round(cum, 5), len(tks), round(tfee, 5), round(paid, 5), round(st["rebate_unpaid"], 5)])
            except Exception as e:
                self.log(f"could not write the rebate report: {e}")
            self.daily_report(a, b, rb, tfee)
            st["period_start"] = b
            st["next_cut"] = self.next_cut_after(b)
            self.dirty = True

    def daily_report(self, a, b, rb, tfee):
        """the 24-hour PnL update (same cut as the rebate report): trades closed in the period, PnL, rebate, fees, equity"""
        st = self.st
        cl = [c for c in st["closed"] if a <= c[0] < b]
        cnt = lambda r: sum(1 for c in cl if c[4] == r)
        pnl = sum(c[5] for c in cl)
        news = sum(c[5] for c in cl if c[2] == "news")
        opn = sum(c[5] for c in cl if c[2] == "open")
        eq = self.equity
        start = st.get("start_capital", 100.0)
        pend = sum(v["pend"] for v in st["chains"].values() if v["pend"] > 0)
        nopen = sum(1 for sl in st["slots"].values() if sl["status"] == "open")
        total = pnl + rb
        bf = [c for c in cl if len(c) > 6 and c[6]]
        bfs = f" [{len(bf)} of them back-filled from the real trades while the bot was off: PnL {sum(c[5] for c in bf):+.2f}]" if bf else ""
        line = (f"DAILY PNL, 24h to {hm_ke(b)} Nairobi: {len(cl)} trades closed ({cnt('hedged')} hedged, {cnt('miss_lose')} lost leg, {cnt('miss_win')} one leg + win, {cnt('no_fill')} no fill){bfs}; "
                f"trade PnL {pnl:+.2f} (news {news:+.2f}, US open {opn:+.2f}; taker fees {tfee:.2f} already deducted) + maker rebate {rb:+.2f} = day total {total:+.2f}. "
                f"Equity ${eq:.2f} (free cash ${st['cash']:.2f}, in {nopen} open trades ${st['locked']:.2f}), {(eq / start - 1) * 100:+.1f}% since start; recovery owed ${pend:.2f}")
        self.log("*** " + line)
        try:
            open(self.day_log, "a", encoding="utf-8").write(f"{datetime.now(KE):%Y-%m-%d %H:%M:%S} KE | {line}\n")
            keep_header(self.day_csv, DAILY_HEAD)
            new = not os.path.exists(self.day_csv)
            with open(self.day_csv, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(DAILY_HEAD)
                w.writerow([hm_ke(a), hm_ke(b), len(cl), cnt("hedged"), cnt("miss_lose"), cnt("miss_win"), cnt("no_fill"), round(pnl, 4), round(news, 4), round(opn, 4), round(rb, 4),
                            round(tfee, 4), round(total, 4), round(eq, 4), round(st["cash"], 4), round(pend, 4), nopen, round((eq / start - 1) * 100, 2)])
        except Exception as e:
            self.log(f"could not write the daily report: {e}")
        if self.notify:
            try:
                self.notify(line)
            except Exception:
                pass
        st["closed"] = [c for c in st["closed"] if c[0] >= b - 86400 * 3]

    # ---- alerts that only need the clock (pure; the listener thread handles the network part)
    def clock_alerts(self, now):
        msgs = []
        rel = {(d, k): REL_TIME[k] for d, k in self.cal.events()}
        today = et_date(now)
        for (d, k), (rh, rm) in rel.items():
            if abs((d - today).days) > 3:
                continue
            ch = event_chains(k, d)[0]
            t0, tr = first_start(ch), et_epoch(d, rh, rm)
            if t0 - 86400 * 2 > now or tr + 600 < now:
                continue
            to = t0 - self.cfg["lead"]
            for key, when, text in ((f"{k}{d}-60", to - 3600, f"60 min until the first {k} orders go in"), (f"{k}{d}-5", to - 300, f"5 min until the first {k} orders go in"),
                                     (f"{k}{d}-rel", tr - 60, f"{k} RELEASE in 1 minute")):
                if when <= now < when + 600 and key not in self.st["alerts"]:
                    self.st["alerts"].append(key)
                    self.dirty = True
                    msgs.append(f"{text}: orders {stamp(to)}, first candle {stamp(t0)}, release {stamp(tr)}")
        last = self.cal.last_date()
        if last and (last - et_date(now)).days < 30:
            key = f"cal-low-{et_date(now)}"
            if key not in self.st["alerts"]:
                self.st["alerts"].append(key)
                self.dirty = True
                msgs.append(f"ALERT calendar runs out on {last:%d %b %Y}: run  py paper_news.py calendar  or add dates to calendar.json")
        self.st["alerts"] = self.st["alerts"][-300:]
        return msgs


def alert_windows(cal, now):
    """times the bot must be awake for the calendar alerts: 60 min before the first orders, the release itself, the 'report published?' check right after and 30 min after the release"""
    out = []
    today = et_date(now)
    for d, k in cal.events():
        if abs((d - today).days) > 3:
            continue
        ch = event_chains(k, d)[0]
        to = first_start(ch) - 300
        rh, rm = REL_TIME[k]
        tr = et_epoch(d, rh, rm)
        out += [(to - 3600 - 120, to - 3600 + 420), (tr - 150, tr + 300)]
        if k != "FOMC":
            out += [(tr + 60, tr + 420), (tr + 1800, tr + 2100)]
    return sorted(out)


# ------------------------------------------------------------------------------------------------ the news listener (network part)
class Listener:
    def __init__(self, cal, fetch, notify, state, every=6 * 3600):
        self.cal, self.fetch, self.notify, self.state, self.every = cal, fetch, notify, state, every
        self.last_refresh = int(state.get("cal_refresh") or 0)         # remembered across restarts (the bot sleeps and wakes)
        self.confirmed = set()

    def tick(self, now):
        today = et_date(now)
        if now - self.last_refresh >= self.every:
            self.last_refresh = now
            self.state["cal_refresh"] = int(now)
            for m in self.cal.refresh(self.fetch, today):
                key = f"cal-{today}-{zlib.crc32(m.encode()) % 10**8}"
                if key in self.state["alerts"]:
                    continue                                              # the same calendar message is sent once a day, not on every wake-up
                self.state["alerts"].append(key)
                self.notify(m)
        for d, kind in self.cal.events():
            if kind == "FOMC" or d != today:
                continue
            tr = et_epoch(d, 8, 30)
            key = f"{kind}{d}"
            if key in self.confirmed or key + "-conf" in self.state["alerts"] or now < tr + 90:
                continue
            html = self.fetch(BLS_RELEASE[kind])
            t = text_of(html) if html else ""
            tag = f"{datetime(d.year, d.month, d.day):%B} {d.day}, {d.year}"
            if tag in t:
                self.confirmed.add(key)
                self.state["alerts"].append(key + "-conf")
                self.notify(f"{kind} report PUBLISHED ({tag}) - the {stamp(tr)} release happened; the hourly candles around it are live.")
            elif now > tr + 1800:
                self.state["alerts"].append(key + "-conf")
                self.notify(f"ALERT {kind} report NOT confirmed on the BLS site 30 min after {stamp(tr)} - it may be postponed. Check by hand; this block's trades are on paper only.")


def make_notifier(log, topic):
    def post(msg):
        try:
            import requests
            r = requests.post(f"https://ntfy.sh/{topic}", data=msg.encode("utf-8"), headers={"Title": "Paper trader"}, timeout=10)
            if not r.ok:
                log(f"(phone alert not delivered: HTTP {r.status_code})")
            return r.ok
        except Exception as e:
            log(f"(phone alert not delivered: {type(e).__name__})")
            return False

    threads = []

    def notify(msg):
        log(f"*** {msg}")
        if topic:
            th = threading.Thread(target=post, args=(msg,), daemon=True)         # never hold up the trading loop
            th.start()
            threads.append(th)
            del threads[:-50]

    def flush(timeout=15):
        """before the program exits (sleep): wait until the phone alerts have really been sent"""
        end = time.time() + timeout
        for th in list(threads):
            th.join(max(0.1, end - time.time()))
    notify.post = post
    notify.flush = flush
    return notify


# ------------------------------------------------------------------------------------------------ commands
def cfg_from(args):
    return {"capital": float(args.get("capital", 100)), "stake": float(args.get("stake", 0.20)), "cap": float(args.get("cap", 1.00)),
            "poll": float(args.get("poll", 2)), "recwait": int(args.get("recwait", 180)), "maxlate": int(args.get("maxlate", 300)),
            "minstake": float(args.get("minstake", 5)), "open_on": args.get("open", "1") != "0", "recovery": args.get("recovery", "1") != "0",
            "ntfy": args.get("ntfy", ""), "recov_tfs": tuple(x for x in args.get("recov_tfs", "1h").split(",") if x),
            "lead": int(args.get("lead", 300)), "base": "total" if args.get("base", "free") == "total" else "free", "rebate": float(args.get("rebate", 0.20)), "rebate_hour": int(args.get("rebate_hour", 0)),
            "backfill": args.get("backfill", "1") != "0", "tradealerts": args.get("tradealerts", "1") != "0", "early": args.get("early", "1") != "0", "rest": args.get("rest", "0") == "1", "wake": int(args.get("wake", 6000)), "bf_days": int(args.get("bf_days", 5)), "bf_delay": int(args.get("bf_delay", 150))}


def logger():
    lock = threading.Lock()

    def log(msg):
        line = f"{datetime.now(KE):%Y-%m-%d %H:%M:%S} KE | {msg}"
        with lock:
            print(line)
            try:
                open(LOG_FILE, "a", encoding="utf-8").write(line + "\n")
            except Exception:
                pass
    return log


def cmd_schedule(args):
    days = int(args.get("days", 45))
    cal = Calendar()
    now = int(time.time())
    d0 = et_date(now)
    chains = plan_chains(cal, d0, d0 + timedelta(days=days), open_on=args.get("open", "1") != "0")
    rows = sorted(((ch.slots[0][0], ch) for ch in chains), key=lambda x: (x[0], x[1].cid))
    print(f"Next {days} days (Nairobi time first, New York time in brackets). Recovery candles only trade after a loss.\n")
    # group by release
    for d, kind in cal.events():
        if not (d0 <= d <= d0 + timedelta(days=days)):
            continue
        chs = event_chains(kind, d)
        tr = et_epoch(d, *REL_TIME[kind])
        print(f"{kind:4s} {d:%a %d %b %Y}   release {stamp(tr)}")
        h = chs[0].slots
        print(f"     hourly : {stamp(h[0][0])}  ->  {datetime.fromtimestamp(h[5][1], KE):%H:%M} Nairobi   (6 candles; recovery candle {datetime.fromtimestamp(h[6][0], KE):%H:%M} only after a loss)")
        s4 = chs[1].slots[0]
        print(f"     4-hour : {stamp(s4[0])}  ->  {datetime.fromtimestamp(s4[1], KE):%H:%M} Nairobi")
        s1 = chs[2].slots[0]
        print(f"     daily  : {stamp(s1[0])}  ->  {stamp(s1[1])}")
    opens = [c for _, c in rows if c.stream == "open" and c.slots[0][0] > now]
    if opens:
        print(f"\nUS open (09:00-10:00 ET, weekdays without a release or US holiday): {len(opens)} candles in this period. First ones:")
        for c in opens[:6]:
            print(f"     {stamp(c.slots[0][0])}")
        print(f"     ... every weekday at {datetime.fromtimestamp(opens[0].slots[0][0], KE):%H:%M} Nairobi now (16:00 in US summer time)")
    last = cal.last_date()
    print(f"\nCalendar covers releases up to {last:%d %b %Y}." if last else "")


def cmd_calendar(args):
    cal = Calendar()
    net = Net()
    today = et_date(int(time.time()))
    print("Refreshing the release calendar online ...")
    for m in cal.refresh(net.fetch_page, today):
        print("  " + m)
    print("\nUpcoming releases:")
    for d, k in cal.events():
        if d >= today:
            tr = et_epoch(d, *REL_TIME[k])
            print(f"  {k:4s} {d:%a %d %b %Y}  {stamp(tr)}")


def cmd_run(args):
    cfg = cfg_from(args)
    log = logger()
    net = Net()
    cal = Calendar()
    state = None
    if os.path.exists(STATE_JSON):
        try:
            state = json.load(open(STATE_JSON, encoding="utf-8"))
            log(f"resumed from {STATE_JSON}: equity ${state['cash'] + state['locked']:.2f}")
        except Exception:
            state = None
    eng = Engine(cfg, net, cal, state, log)
    eng.st["wake_at"] = None
    eng.dirty = True                                              # saved at once, so a stale wake-up time never stays in the file
    notify = make_notifier(log, cfg["ntfy"])
    eng.notify = notify
    lst = Listener(cal, net.fetch_page, notify, eng.st)
    log(f"PAPER TRADER started - NO ORDERS ARE PLACED. capital ${eng.equity:.2f}, stake {cfg['stake']:.0%} of {'free cash' if cfg['base'] == 'free' else 'total capital (never more than the free cash)'}, orders {cfg['lead'] // 60} min before each candle, recovery {'10x loss on %s (cap %.0f%%)' % (','.join(cfg['recov_tfs']), cfg['cap'] * 100) if cfg['recovery'] else 'off'}, "
        f"US open {'on' if cfg['open_on'] else 'off'}. Times are Nairobi time first.")
    nxt = sorted((d, k) for d, k in cal.events() if d >= et_date(int(time.time())))[:4]
    for d, k in nxt:
        log(f"upcoming: {k} {d:%a %d %b} release {stamp(et_epoch(d, *REL_TIME[k]))}")
    stop = threading.Event()

    first_tick = threading.Event()
    t_start = time.time()

    def bg():
        while not stop.is_set():
            try:
                lst.tick(int(time.time()))
            except Exception as e:
                log(f"listener error: {e}")
            first_tick.set()
            stop.wait(30)

    th = threading.Thread(target=bg, daemon=True)
    th.start()
    n = 0
    try:
        while True:
            t0 = time.time()
            try:
                eng.step(int(t0))
                for m in eng.clock_alerts(int(t0)):
                    notify(m)
            except Exception as e:
                log(f"loop error: {type(e).__name__}: {e}")
            n += 1
            try:
                w = eng.next_wake(int(t0))
            except Exception as e:
                w = None
                log(f"sleep check error: {type(e).__name__}: {e}")
            if w and not (first_tick.is_set() or time.time() - t_start > 90):
                w = None                                              # the calendar check of this wake-up has not finished yet
            if w:
                eng.st["wake_at"], eng.st["last_seen"] = w, int(time.time())
                eng.save()
                msg = f"SLEEP: nothing to watch for a long while; the bot restarts at about {stamp(w)}, {cfg['wake'] // 60} min before the next thing it needs to do. Open orders stay in the state; their fills are re-checked from the real trades on waking. Equity ${eng.equity:.2f}"
                notify(msg)
                stop.set()
                notify.flush(20)
                return
            if n % 300 == 1:
                live = sum(1 for s in eng.st["slots"].values() if s["status"] == "open")
                log(f"alive: equity ${eng.equity:.2f}, {live} trades open, {eng.st['trades']} trades so far")
            time.sleep(max(0.3, cfg["poll"] - (time.time() - t0)))
    except KeyboardInterrupt:
        stop.set()
        eng.save()
        log("stopped by user (state saved)")
        notify.flush(10)


def cmd_notifytest(args):
    topic = args.get("ntfy", "")
    if not topic:
        print("usage: py paper_news.py notifytest ntfy=<your-topic>")
        return
    log = logger()
    n = make_notifier(log, topic)
    ok = n.post(f"Test from the paper trader at {stamp(int(time.time()))}. If you can read this on your phone, alerts work.")
    log("sent to ntfy.sh - check your phone (the topic must match the one you subscribed to in the app)" if ok else "NOT sent - check this computer's internet connection")


def cmd_status(args):
    try:
        st = json.load(open(STATE_JSON, encoding="utf-8"))
    except Exception:
        print("no state yet: run  py paper_news.py run")
        return
    eq = st["cash"] + st["locked"]
    print(f"Equity ${eq:.2f} (FREE cash ${st['cash']:.2f}, in open trades ${st['locked']:.2f})   start ${st.get('start_capital', 100):.0f}   trades {st['trades']}")
    rb = sum(r[5] for r in st.get("rebates", []))
    tf = sum(r[5] for r in st.get("takerfees", []))
    print(f"Maker rebate earned so far ${rb:.4f} (paid out ${st.get('rebate_paid', 0):.2f}, unpaid ${st.get('rebate_unpaid', 0):.4f} + today's not yet reported); taker fees paid ${tf:.4f}")
    if st.get("next_cut"):
        print(f"Next 24h rebate report: {stamp(st['next_cut'])}")
    now = int(time.time())
    op = [s for s in st["slots"].values() if s["status"] == "open"]
    print(f"\nOpen trades: {len(op)}")
    for s in op:
        p = s["pos"]
        legs = ",".join(k for k, l in p["v"]["bid"].items() if l) or "none sold yet"
        print(f"  #{p['n']} {s['tf']} {s['label']}  candle {stamp(s['start'])}  stake ${p['stake']:.2f}  legs sold: {legs}")
    pend = {c: v["pend"] for c, v in st["chains"].items() if v["pend"] > 0}
    if pend:
        print("\nPending losses (recovery owed): " + ", ".join(f"{c} ${v:.2f}" for c, v in pend.items()))
    fut = sorted((s["start"], s) for s in st["slots"].values() if s["status"] == "future" and s["start"] > now)[:8]
    print("\nNext candles:")
    for t, s in fut:
        print(f"  {stamp(t)}  {s['tf']}  {s['label']}  ({'scheduled' if s['sched'] else 'recovery, only after a loss'})")


def wilson_low(k, n, z=1.645):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d


def summarize(rows):
    L = []
    if not rows:
        return "No finished trades yet."
    eq = [float(r["equity_after"]) for r in rows]
    start = float(rows[0]["equity_before"])
    peak, mdd = start, 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak)
    L.append(f"PAPER RESULTS: {len(rows)} trades, {rows[0]['start_ke']} to {rows[-1]['start_ke']} (Nairobi).  Start ${start:.2f} -> equity ${eq[-1]:.2f}  ({(eq[-1] / start - 1) * 100:+.1f}%), worst drawdown {mdd:.0%}")
    L.append("")

    def block(name, rs):
        n = len(rs)
        if not n:
            return
        hed = sum(1 for r in rs if r["result"] == "hedged")
        mid = sum(1 for r in rs if r["result_mid"] == "hedged")
        pnl = sum(float(r["pnl"]) for r in rs)
        lose = sum(1 for r in rs if r["result"] == "miss_lose")
        runl = best_run = 0
        for r in rs:
            runl = runl + 1 if r["result"] == "miss_lose" else 0
            best_run = max(best_run, runl)
        two = sum(1 for a, b in zip(rs, rs[1:]) if a["result"] == "miss_lose" and b["result"] == "miss_lose")
        L.append(f"{name:28s} n={n:3d}  hedge rate {hed / n:5.1%} (needs {BREAK_EVEN:.1%})  95% lower bound {wilson_low(hed, n):5.1%}   mid-price rule {mid / n:5.1%}   PnL ${pnl:+8.2f}   losses {lose}, longest loss run {best_run}, back-to-back loss pairs {two}")

    for nm, f in (("ALL", lambda r: True), ("NEWS - all markets", lambda r: r["stream"] == "news"), ("  news hourly", lambda r: r["stream"] == "news" and r["market"] == "1h"),
                  ("  news 4-hour", lambda r: r["stream"] == "news" and r["market"] == "4h"), ("  news daily", lambda r: r["stream"] == "news" and r["market"] == "1d"),
                  ("  news scheduled candles", lambda r: r["stream"] == "news" and r["role"] == "scheduled"), ("  news recovery candles", lambda r: r["stream"] == "news" and r["role"] == "recovery"),
                  ("US OPEN 09:00 ET", lambda r: r["stream"] == "open")):
        block(nm, [r for r in rows if f(r)])
    L.append("")
    rb = sum(float(r.get("maker_rebate") or 0) for r in rows)
    tfee = sum(float(r.get("taker_fee") or 0) for r in rows)
    crossed = sum(1 for r in rows if r.get("crossed") == "1")
    pnl_all = sum(float(r["pnl"]) for r in rows)
    L.append(f"FEES: trade PnL ${pnl_all:+.2f} already includes taker fees (${tfee:.2f} on {crossed} trades whose sell went through the book at once). "
             f"Maker rebate (20% of the fee equivalent, paid daily): ${rb:+.2f}  ->  PnL including rebate ${pnl_all + rb:+.2f}")
    L.append("")
    L.append("GO / NO-GO (agreed rules; the release hours need ~60 trades, about 3 months):")
    for nm, f in (("news hourly (release hours)", lambda r: r["stream"] == "news" and r["market"] == "1h" and r["role"] == "scheduled"), ("US open 09:00", lambda r: r["stream"] == "open")):
        rs = [r for r in rows if f(r)]
        n = len(rs)
        hed = sum(1 for r in rs if r["result"] == "hedged")
        if n < 60:
            verdict = f"keep going ({n}/60 trades" + (f", {hed / n:.0%} so far)" if n else ")")
        else:
            rate = hed / n
            lo = wilson_low(hed, n)
            if rate < 0.84:
                verdict = f"STOP - {rate:.1%} is below 84% after {n} trades"
            elif rate >= 0.85 and (n >= 120 and lo > BREAK_EVEN):
                verdict = f"GO - {rate:.1%} over {n} trades and the 95% lower bound {lo:.1%} is above break-even"
            elif rate >= 0.85:
                verdict = f"GO CANDIDATE - {rate:.1%} over {n} trades; confirm at 120 trades (lower bound now {lo:.1%})"
            else:
                verdict = f"UNDECIDED - {rate:.1%} (between 84% and 85%); keep going"
        L.append(f"  {nm:30s} {verdict}")
    L.append("Paper fills are easier than real ones: start real money at 5-10% stake, not 20%.")
    return "\n".join(L)


def cmd_summary(args):
    if not os.path.exists(TRADES_CSV):
        print("no trades yet")
        return
    rows = list(csv.DictReader(open(TRADES_CSV, encoding="utf-8")))
    txt = summarize(rows)
    print(txt)
    open(SUMMARY, "w", encoding="utf-8").write(txt + "\n")
    print(f"\nsaved {SUMMARY}")


# ------------------------------------------------------------------------------------------------ self test (fake markets)
class FakeNet:
    """scripted markets: script(tf,start,t)->price of Up in [0,1]; winner = Up if the last price > 0.5"""
    def __init__(self, script, delay=40):
        self.script, self.delay, self.t = script, delay, 0

    def load_market(self, tf, start):
        return {"up": f"U|{tf}|{start}", "down": f"D|{tf}|{start}"}

    def books(self, tokens):
        out = {}
        for tk in tokens:
            side, tf, st = tk.split("|")
            st = int(st)
            p = self.script(tf, st, self.t)
            p = p if side == "U" else 1 - p
            out[tk] = {"bids": [(round(max(0.01, p - 0.01), 3), 500.0)], "asks": [(round(min(0.99, p + 0.01), 3), 500.0)]}
        return out

    def trades(self, tf, start):
        end = start + {"1h": 3600, "4h": 14400, "1d": 86400}[tf]
        if self.t < start:
            return None
        out = []
        for ts in range(start, min(end, self.t + 1), 10):
            p = self.script(tf, start, ts)
            out.append((ts, "up", round(p, 3), 500.0))
            out.append((ts, "down", round(1 - p, 3), 500.0))
        return out

    def winner(self, tf, start):
        end = start + {"1h": 3600, "4h": 14400, "1d": 86400}[tf]
        if self.t < end + self.delay:
            return None
        return "up" if self.script(tf, start, end - 1) > 0.5 else "down"


def selftest():
    import tempfile
    tmp = tempfile.mkdtemp()
    sp, cp = os.path.join(tmp, "s.json"), os.path.join(tmp, "t.csv")
    # --- parsing
    html = ("<table><tr><td>Oct. 2026</td><td>Nov. 13, 2026</td><td>08:30 AM</td></tr><tr><td>Nov. 2026</td><td>Dec. 15, 2026</td><td>08:30 AM</td></tr>"
            "<tr><td>Dec. 2026</td><td>Jan. 14, 2027</td><td>08:30 AM</td></tr><tr><td>Last modified Nov. 12, 2026</td></tr></table>")
    got = parse_bls(html)
    assert got == {date(2026, 11, 13), date(2026, 12, 15), date(2027, 1, 14)}, got
    fed = "<h4>2026 FOMC Meetings</h4><div>January</div><div>27-28</div><div>March</div><div>17-18*</div><div>April</div><div>28-29</div><h4>2027 FOMC Meetings</h4><div>January</div><div>26-27</div>"
    fm = parse_fomc(fed)
    assert fm == {date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2027, 1, 27)}, fm
    # --- times: Nairobi shown for winter (EST, +8h) and summer (EDT, +7h)
    assert datetime.fromtimestamp(et_epoch(date(2026, 12, 10), 6), KE).strftime("%H:%M") == "14:00"
    assert datetime.fromtimestamp(et_epoch(date(2026, 7, 14), 6), KE).strftime("%H:%M") == "13:00"
    assert datetime.fromtimestamp(et_epoch(date(2026, 12, 9), 12), KE).strftime("%H:%M") == "20:00"
    # --- chains: hourly/4h/daily slots
    ch = event_chains("CPI", date(2026, 12, 10))
    assert [datetime.fromtimestamp(s, KE).strftime("%H:%M") for s, e in ch[0].slots] == ["14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
    assert ch[1].slots[0][0] == et_epoch(date(2026, 12, 10), 8) and ch[1].slots[0][1] - ch[1].slots[0][0] == 14400
    assert ch[2].slots[0] == (et_epoch(date(2026, 12, 9), 12), et_epoch(date(2026, 12, 10), 12))
    fc = event_chains("FOMC", date(2026, 12, 9))
    assert fc[2].slots[0][0] == et_epoch(date(2026, 12, 9), 12) and fc[0].slots[0][0] == et_epoch(date(2026, 12, 9), 12)
    # --- calendar: user add/remove, open-stream days (no release days, no weekends, no holidays)
    ucal = os.path.join(tmp, "cal.json")
    json.dump({"add": [{"date": "2027-01-08", "kind": "NFP"}], "remove": ["2026-12-04"]}, open(ucal, "w"))
    cal = Calendar(ucal, os.path.join(tmp, "cc.json"))
    ev = cal.events()
    assert (date(2027, 1, 8), "NFP") in ev and (date(2026, 12, 4), "NFP") not in ev
    chains = plan_chains(cal, date(2026, 12, 7), date(2026, 12, 13), True)
    opens = sorted(c.cid for c in chains if c.stream == "open")
    assert opens == ["OPEN-2026-12-07", "OPEN-2026-12-08", "OPEN-2026-12-11"], opens    # Dec 9 FOMC and Dec 10 CPI are release days; weekend skipped
    hol = plan_chains(cal, date(2026, 11, 25), date(2026, 11, 27), True)
    assert sorted(c.cid for c in hol if c.stream == "open") == ["OPEN-2026-11-25", "OPEN-2026-11-27"]   # Thanksgiving (Nov 26) skipped

    # --- full run: CPI day 2026-11-10, scripted prices
    def script(tf, start, t):
        k = (start // 3600) % 6
        end = start + {"1h": 3600, "4h": 14400, "1d": 86400}[tf]
        frac = (t - start) / (end - start)
        if tf == "1h" and start == et_epoch(date(2026, 11, 11), 9):
            return 0.62                      # the US-open candle is already above 55c when the orders go in: Up sells AT ONCE as a taker
        if t < start:
            return 0.5                       # before the open the market sits at 50c
        if tf == "1h":
            hr = (start - et_epoch(date(2026, 11, 10), 6)) // 3600
            if hr == 0:                      # 06:00 candle: both legs touch 55c -> HEDGED
                return 0.5 + 0.10 * math.sin(frac * 6.3)
            if hr == 1:                      # 07:00: one-way rally and Up wins -> Up leg sold at 55c, Down loses -> MISS_LOSE
                return 0.5 + 0.45 * min(1, frac * 3)
            if hr in (2, 3):                 # the two candles after the loss: both hedge (recovery stakes win the loss back)
                return 0.5 + 0.10 * math.sin(frac * 6.3)
            return 0.5 + 0.02 * math.sin(frac * 6.3)          # others: nothing reaches 55c -> NO_FILL
        if tf == "4h":
            return 0.5 + 0.10 * math.sin(frac * 6.3)
        return 0.5 + 0.02 * math.sin(frac * 6.3)
    cfg = {"capital": 100.0, "stake": 0.20, "cap": 0.50, "poll": 2, "recwait": 180, "maxlate": 300, "minstake": 1.0, "open_on": True, "recovery": True, "ntfy": "", "recov_tfs": ("1h",), "lead": 300, "rebate": 0.20, "rebate_hour": 0, "base": "free"}
    net = FakeNet(script)
    msgs = []
    eng = Engine(cfg, net, cal, None, msgs.append, sp, cp)
    t0 = et_epoch(date(2026, 11, 9), 11, 40)
    t1 = et_epoch(date(2026, 11, 11), 13, 0)
    alerts = []
    t = t0
    while t < t1:
        net.t = t
        eng.step(t)
        alerts += eng.clock_alerts(t)
        t += 10 if t < et_epoch(date(2026, 11, 10), 13) else 120
        # invariants
        assert abs(eng.st["cash"] + eng.st["locked"] - eng.equity) < 1e-9 and eng.st["cash"] >= -1e-6
        assert abs(sum(sl["pos"]["stake"] for sl in eng.st["slots"].values() if sl["status"] == "open") - eng.st["locked"]) < 1e-6
    rows = list(csv.DictReader(open(cp)))
    h = [r for r in rows if r["market"] == "1h" and r["stream"] == "news"]
    fl = lambda r, k: float(r[k])
    # first hourly candle: previous candle none -> orders go in ~5 minutes BEFORE the open; stake = 20% of FREE cash (the daily trade already locked $20)
    assert h[0]["result"] == "hedged" and -310 <= int(h[0]["entry_vs_open_s"]) <= -285, h[0]
    assert abs(fl(h[0], "stake") - 0.2 * fl(h[0], "cash_before")) < 0.02 and abs(fl(h[0], "cash_before") - 80.0) < 0.01, h[0]
    assert abs(fl(h[0], "pnl") - 0.10 * fl(h[0], "stake")) < 0.02
    # maker rebate = 20% of N x 0.07 x 0.55 x 0.45 on each of the two legs
    assert abs(fl(h[0], "maker_rebate") - 2 * 0.20 * 0.07 * 0.55 * 0.45 * fl(h[0], "stake")) < 0.005 and fl(h[0], "taker_fee") == 0, h[0]
    assert abs(fl(h[0], "pnl_incl_rebate") - fl(h[0], "pnl") - fl(h[0], "maker_rebate")) < 0.001
    # second candle: previous one hedged early -> placed before the open too; it is the loss
    assert h[1]["result"] == "miss_lose" and abs(fl(h[1], "pnl") + 0.45 * fl(h[1], "stake")) < 0.05 and int(h[1]["entry_vs_open_s"]) < -200, h[1]
    assert abs(fl(h[1], "maker_rebate") - 0.20 * 0.07 * 0.55 * 0.45 * fl(h[1], "stake")) < 0.005         # only ONE leg was sold: half the rebate
    loss = -fl(h[1], "pnl")
    # third candle: the previous one has ONE leg sold (a loss in the making) -> it waits for the result, so it is placed AFTER the open, with the 10x stake
    assert int(h[2]["entry_vs_open_s"]) >= 0, h[2]
    want = min(0.5 * fl(h[2], "cash_before"), loss / 0.10)
    assert abs(fl(h[2], "stake") - want) < 0.02 and abs(fl(h[2], "pending_loss") - loss) < 0.02, (h[2]["stake"], want)
    assert h[2]["result"] == "hedged" and h[2]["role"] == "scheduled" and h[3]["result"] == "hedged"
    # fourth candle: recovery lasts ONE candle -> any rest of the loss is taken, the stake is the normal 20% of free cash, no pending loss
    assert int(h[3]["entry_vs_open_s"]) < -200, h[3]
    assert fl(h[3], "pending_loss") == 0 and abs(fl(h[3], "stake") - 0.2 * fl(h[3], "cash_before")) < 0.02, h[3]
    assert len([r for r in h if r["role"] == "scheduled"]) == 6, [r["role"] for r in h]
    rec = [r for r in h if r["role"] == "recovery"]
    assert len(rec) == 0                                                  # the 6th candle did not lose, so no 7th candle
    assert {r["market"] for r in rows if r["stream"] == "news"} == {"1h", "4h", "1d"}
    # open stream on 2026-11-11 (Wednesday, no release): one trade at 09:00 ET; Up was already above 55c: sold AT ONCE as a taker (fee, no rebate)
    op = [r for r in rows if r["stream"] == "open"]
    assert len(op) == 1 and op[0]["start_et"].endswith("09:00") and op[0]["start_ke"].endswith("17:00") and op[0]["start_et"].startswith("2026-11-11"), op
    o = op[0]
    assert o["crossed"] == "1" and o["up_sold"] == "0.61" and o["down_sold"] == "" and o["result"] == "miss_lose", o
    assert abs(fl(o, "taker_fee") - fl(o, "stake") * 0.07 * 0.61 * 0.39) < 0.001 and fl(o, "maker_rebate") == 0, o
    assert abs(fl(o, "pnl") - (0.61 * fl(o, "stake") - fl(o, "taker_fee") - fl(o, "stake"))) < 0.005, o
    # daily rebate report: written at 00:00 Nairobi time; the reports + the not-yet-reported rest add up to the ledger
    reb = list(csv.DictReader(open(os.path.join(tmp, "paper_news_rebates.csv"))))
    assert len(reb) == 2 and reb[0]["period_end_ke"].endswith("00:00") and reb[1]["period_start_ke"].endswith("00:00"), reb
    ledger = sum(r[5] for r in eng.st["rebates"])
    assert abs(sum(float(r["maker_rebate_usd"]) for r in reb) + sum(r[5] for r in eng.st["rebates"] if r[0] >= eng.st["period_start"]) - ledger) < 1e-3
    assert abs(ledger - sum(float(r["maker_rebate"]) for r in rows)) < 0.01, (ledger, sum(float(r["maker_rebate"]) for r in rows))
    day = list(csv.DictReader(open(os.path.join(tmp, "paper_news_daily.csv"))))
    assert len(day) == 2 and int(day[0]["trades_closed"]) + int(day[1]["trades_closed"]) <= len(rows), day
    assert abs(float(day[0]["day_total_usd"]) - float(day[0]["trade_pnl_usd"]) - float(day[0]["maker_rebate_usd"])) < 1e-3
    assert "DAILY PNL" in open(os.path.join(tmp, "paper_news_daily.log")).read()
    assert os.path.getsize(os.path.join(tmp, "paper_news_rebates.log")) > 50 and reb[-1]["taker_sells"] in ("0", "1")
    assert any("60 min until the first CPI orders go in" in a for a in alerts) and any("CPI RELEASE" in a for a in alerts), alerts
    assert all(r["start_ke"] and r["end_ke"] for r in rows)
    # persistence: a new engine from the saved state continues without re-entering anything
    st2 = json.load(open(sp))
    eng2 = Engine(cfg, net, cal, st2, msgs.append, sp, cp)
    n0 = len(list(csv.DictReader(open(cp))))
    net.t = t1
    eng2.step(t1)
    assert len(list(csv.DictReader(open(cp)))) == n0
    # --- base=total: 20% of TOTAL capital (locked money included) but never more than the free cash
    cfgT = dict(cfg, base="total", recovery=False)
    engT = Engine(cfgT, FakeNet(script), cal, None, msgs.append, os.path.join(tmp, "sT.json"), os.path.join(tmp, "tT.csv"))
    netT = engT.net
    tt = et_epoch(date(2026, 11, 9), 11, 40)
    while tt < et_epoch(date(2026, 11, 10), 8, 30):
        netT.t = tt
        engT.step(tt)
        tt += 10
    rT = list(csv.DictReader(open(os.path.join(tmp, "tT.csv"))))
    hT = [r for r in rT if r["market"] == "1h"]
    assert abs(float(hT[0]["stake"]) - 20.0) < 0.01 and abs(float(hT[0]["cash_before"]) - 80.0) < 0.01, hT[0]      # 20% of $100 total (free cash was only $80)
    assert all(float(r["stake"]) <= float(r["cash_before"]) + 1e-6 for r in rT)
    # --- late start: engine started in the middle of the block skips candles that are too late
    eng3 = Engine(cfg, FakeNet(script), cal, None, msgs.append, os.path.join(tmp, "s3.json"), os.path.join(tmp, "t3.csv"))
    nt = FakeNet(script)
    nt.t = et_epoch(date(2026, 11, 10), 7, 30)
    eng3.net = nt
    eng3.step(nt.t)
    assert eng3.st["trades"] == 0
    # --- back-fill: the same days traded live, but the bot is OFF from 04:00 ET on 10 Nov until after the 11 Nov open; the missed candles are rebuilt from the real trades
    cfgB = dict(cfg, backfill=True, bf_days=5, bf_delay=150)
    netB = FakeNet(script)
    spB, cpB = os.path.join(tmp, "sB.json"), os.path.join(tmp, "tB.csv")
    engB = Engine(cfgB, netB, cal, None, msgs.append, spB, cpB)
    tb = t0
    while tb < et_epoch(date(2026, 11, 10), 4, 0):
        netB.t = tb
        engB.step(tb)
        tb += 10 if tb > et_epoch(date(2026, 11, 9), 11, 59) else 60
    engB.save() if hasattr(engB, "save") else None
    engB = Engine(cfgB, netB, cal, json.load(open(spB)), msgs.append, spB, cpB)           # laptop switched on again
    tb = et_epoch(date(2026, 11, 11), 8, 0)
    while tb < t1:
        netB.t = tb
        engB.step(tb)
        tb += 60
        assert abs(engB.st["cash"] + engB.st["locked"] - engB.equity) < 1e-9 and engB.st["cash"] >= -1e-6
    rB = list(csv.DictReader(open(cpB)))
    hB = [r for r in rB if r["market"] == "1h" and r["stream"] == "news"]
    assert len(hB) == len(h), (len(hB), len(h))
    assert any(r["source"] == "backfill" for r in hB), [r["source"] for r in hB]
    for a_, b_ in zip(h, hB):
        assert a_["result"] == b_["result"], (a_["start_et"], a_["result"], b_["result"])
        assert abs(float(a_["pending_loss"]) - float(b_["pending_loss"])) < 0.02, (a_["start_et"], a_["pending_loss"], b_["pending_loss"])
    assert [r["role"] for r in hB] == [r["role"] for r in h]
    print("backfill check: " + ", ".join(f"{r['start_ke'][-5:]}:{r['result']}/{r['source']}/${r['stake']}" for r in hB))
    # --- early orders + sleeping: the next candle's orders go in as soon as the hedge before it is complete; the bot then sleeps until 15 min before the next candle
    print("entry vs open (s) of the live hourly candles: " + ", ".join(f"{r['start_ke'][-5:]}:{r['entry_vs_open_s']}" for r in h))
    assert int(h[1]["entry_vs_open_s"]) < -1000 and int(h[3]["entry_vs_open_s"]) < -600, [r["entry_vs_open_s"] for r in h]         # right after the hedge before (not 5 min before)
    assert int(h[4]["entry_vs_open_s"]) < -600 and -330 < int(h[5]["entry_vs_open_s"]) < -250                                        # the 19:00 candle follows a no-fill: the 5-minute rule
    cfgR = dict(cfg, rest=True, wake=900, early=True)
    netR = FakeNet(script)
    spR, cpR = os.path.join(tmp, "sR.json"), os.path.join(tmp, "tR.csv")
    engR = Engine(cfgR, netR, cal, None, msgs.append, spR, cpR)
    tr_, sleeps, awake = t0, [], 0
    while tr_ < t1:
        netR.t = tr_
        engR.step(tr_)
        assert abs(engR.st["cash"] + engR.st["locked"] - engR.equity) < 1e-9 and engR.st["cash"] >= -1e-6
        w = engR.next_wake(tr_)
        if w:
            engR.st["wake_at"], engR.st["last_seen"] = w, tr_
            engR.save()
            sleeps.append((tr_, w))
            assert w - tr_ >= 20 * 60
            tr_ = w                                                                             # the gate wakes the bot at w: a NEW process reads the saved state
            engR = Engine(cfgR, netR, cal, json.load(open(spR)), msgs.append, spR, cpR)
            engR.st["wake_at"] = None
        else:
            awake += 1
            tr_ += 10 if tr_ < et_epoch(date(2026, 11, 10), 13) else 120
    engR.save()
    rR = list(csv.DictReader(open(cpR)))
    hR = [r for r in rR if r["market"] == "1h" and r["stream"] == "news"]
    assert len(sleeps) >= 2, sleeps
    assert [r["result"] for r in hR] == [r["result"] for r in h], ([r["result"] for r in hR], [r["result"] for r in h])
    assert [r["role"] for r in hR] == [r["role"] for r in h]
    assert {r["market"] for r in rR if r["stream"] == "news"} == {"1h", "4h", "1d"}
    print(f"sleep check: {len(sleeps)} sleeps, results equal the always-on run: " + ", ".join(r["result"] for r in hR) + f"; final equity ${engR.equity:.2f} vs always-on ${eng.equity:.2f}")
    # --- listener
    seen = []
    pages = {BLS_PAGES["CPI"]: html, BLS_PAGES["PPI"]: html, BLS_PAGES["NFP"]: html, FED_PAGE: fed,
             BLS_RELEASE["CPI"]: "<p>embargoed until 8:30 a.m. (ET) Thursday, December 10, 2026</p>"}
    lst = Listener(Calendar(os.path.join(tmp, "none.json"), os.path.join(tmp, "c2.json")), pages.get, seen.append, {"alerts": []})
    lst.tick(et_epoch(date(2026, 12, 10), 8, 35))
    assert any("NEW PPI date" in m or "NEW CPI date" in m for m in seen) or any("NOT confirmed" in m for m in seen), seen
    assert any("CPI report PUBLISHED" in m for m in seen), seen
    if os.environ.get("VERBOSE"):
        print("\n".join(msgs))
    # --- summary
    txt = summarize(rows)
    assert "NEWS - all markets" in txt and "GO / NO-GO" in txt and "US OPEN" in txt
    print(txt)
    print(f"\ntrades in the test run: {len(rows)} (news hourly {len(h)}, 4h, daily, open {len(op)}); final equity ${eng.equity:.2f}")
    print("paper_news selftest passed")


def main(argv):
    cmd = argv[0] if argv else ""
    args = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
    {"selftest": lambda: selftest(), "schedule": lambda: cmd_schedule(args), "calendar": lambda: cmd_calendar(args), "run": lambda: cmd_run(args),
     "status": lambda: cmd_status(args), "summary": lambda: cmd_summary(args), "notifytest": lambda: cmd_notifytest(args)}.get(cmd, lambda: print(__doc__))()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    main(sys.argv[1:])

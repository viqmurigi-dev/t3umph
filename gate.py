"""Decides whether the paper trader needs to be running right now (used by the GitHub Actions workflow).
Prints  run=true|false  and  secs=<how long to run>  to $GITHUB_OUTPUT (or stdout).  Env: NOW (epoch, for testing), FORCE_MIN (run that many minutes regardless)."""
import os, sys, time
from datetime import timedelta
import paper_news as pn

LEAD, LOOK, GAP, CAP = 300, 2400, 1800, int(5.6 * 3600)


def windows(now):
    cal = pn.Calendar()
    d = pn.et_date(now)
    w = []
    for c in pn.plan_chains(cal, d - timedelta(days=1), d + timedelta(days=1), True):
        for s, e in c.slots:
            if c.tf == "1h":
                w.append((s - LEAD - 60, e + 180))
            else:                                     # 4h / daily: orders at the start, and the settlement at the end
                w.append((s - LEAD - 60, s + 420))
                w.append((e, e + 300))
    return sorted(w)


def decide(now):
    ws = windows(now)
    cur = None
    for s, e in ws:
        if e < now:
            continue
        if cur is None:
            if s <= now + LOOK:
                cur = [s, e]
            else:
                break
        elif s <= cur[1] + GAP:
            cur[1] = max(cur[1], e)
        else:
            break
    if cur is None or cur[1] - now < 60:
        return False, 0
    return True, int(min(cur[1] - now, CAP))


if __name__ == "__main__":
    now = int(os.environ.get("NOW") or time.time())
    fm = os.environ.get("FORCE_MIN")
    run, secs = (True, int(float(fm) * 60)) if fm else decide(now)
    out = f"run={'true' if run else 'false'}\nsecs={secs}\n"
    if os.environ.get("GITHUB_OUTPUT"):
        open(os.environ["GITHUB_OUTPUT"], "a").write(out)
    print(out.replace("\n", " "), pn.stamp(now))

#!/bin/bash
# Saves the paper account (state, trades, logs) into the repository. Safe when some files do not exist yet.
git config user.name "paper-trader"
git config user.email "paper-trader@users.noreply.github.com"
for f in paper_news_state.json paper_news_trades.csv paper_news_daily.csv paper_news_rebates.csv paper_news_daily.log paper_news_rebates.log paper_news.log calendar_cache.json; do
  if [ -f "$f" ]; then git add -f "$f"; fi          # one file at a time: a missing file must not stop the others
done
git diff --cached --quiet || git commit -q -m "paper trader state $(date -u +%F_%H:%M)"
for i in 1 2 3; do
  if git push -q 2>/dev/null; then echo "saved"; exit 0; fi                       # normal case: just push
  git pull --rebase --autostash -q || true                                       # someone else changed the repository meanwhile: bring it in, then push again
  if git push -q; then echo "saved"; exit 0; fi
  sleep 3
done
echo "SAVE FAILED"; exit 1

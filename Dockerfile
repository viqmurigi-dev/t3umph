FROM python:3.12-slim
WORKDIR /app
COPY paper_news.py .
CMD ["python", "-u", "paper_news.py", "run", "ntfy=btc_signe_1000"]

# syntax=docker/dockerfile:1.7
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DEVFUN_DB_PATH=/data/tcg_telemetry.sqlite
WORKDIR /app
RUN groupadd --system --gid 1001 tcgbot && useradd --system --uid 1001 --gid tcgbot --create-home tcgbot && mkdir -p /data && chown -R tcgbot:tcgbot /app /data
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY --chown=tcgbot:tcgbot config.py tracker.py engine.py telemetry.py bankroll.py runner.py deck.json ./
USER tcgbot
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import os, sqlite3; db=os.environ['DEVFUN_DB_PATH']; conn=sqlite3.connect(db); conn.execute('SELECT 1'); conn.close()" || exit 1
CMD ["python", "runner.py"]

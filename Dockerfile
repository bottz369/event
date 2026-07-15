FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt requirements.txt
COPY bot/requirements.txt bot/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r bot/requirements.txt
COPY . .
CMD ["sh", "-c", "uvicorn bot.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt requirements.txt
COPY bot/requirements.txt bot/requirements.txt
RUN sed -E '/^(streamlit|streamlit-sortables|streamlit-image-coordinates|starlette)==/d' requirements.txt > /tmp/bot-runtime.txt \
    && pip install --no-cache-dir -r /tmp/bot-runtime.txt -r bot/requirements.txt
COPY . .
CMD ["sh", "-c", "uvicorn bot.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

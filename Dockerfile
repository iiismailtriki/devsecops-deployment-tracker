FROM python:3.12-slim

WORKDIR /app

RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY VERSION ./VERSION

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "app.main:app"]

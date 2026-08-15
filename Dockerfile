FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        openjdk-21-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

RUN useradd \
    --create-home \
    --shell /usr/sbin/nologin \
    runner

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /tmp/runner && \
    chown -R runner:runner /app /tmp/runner

USER runner

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

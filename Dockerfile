# Python + Playwright + Chromium base
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Python deps (now includes playwright as a module)
COPY requirements.txt /app/
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt && \
    python -m playwright install --with-deps chromium

# App code
COPY . /app

# Run the app
CMD ["python", "main.py"]

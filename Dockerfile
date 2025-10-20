# Includes Python + Playwright + Chromium + system deps
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Your Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

ENV PYTHONUNBUFFERED=1

# entrypoint
CMD ["python", "main.py"]


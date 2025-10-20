# Python + Playwright + Chromium already installed and wired up
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

# Make logs flush immediately and avoid pip cache bloat
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install your Python deps first to leverage Docker layer cache
COPY requirements.txt /app/
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy the app code
COPY . /app

# (Optional) sanity check Playwright at build time to fail fast if something’s off
RUN python - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    print("Playwright OK:", p.chromium.name)
PY

# Run your app
CMD ["python", "main.py"]


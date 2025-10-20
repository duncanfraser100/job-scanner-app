# Python + Playwright + Chromium already installed
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

# Fast, clean logs & installs
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install your Python deps (Playwright is already in the base image)
COPY requirements.txt /app/
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy the app code
COPY . /app

# Run your app
CMD ["python", "main.py"]

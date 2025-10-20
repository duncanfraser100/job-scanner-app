FROM mcr.microsoft.com/devcontainers/python:3.11

RUN apt-get update && apt-get install -y wget gnupg --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Playwright + browser
RUN pip install --no-cache-dir playwright==1.48.0 && \
    playwright install --with-deps chromium

COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]

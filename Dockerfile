FROM mcr.microsoft.com/devcontainers/python:3.11

# System deps for Playwright (optional); comment out if you avoid headless browser scraping
RUN apt-get update && apt-get install -y wget gnupg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ /app/src/
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main"]



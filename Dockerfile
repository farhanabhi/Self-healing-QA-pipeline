# Official Playwright image ships Chromium/Firefox/WebKit + all OS deps
# pre-installed, so we don't need a fragile `apt-get` list here.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    ENVIRONMENT=docker

CMD ["pytest", "-n", "auto", "--dist=loadgroup", \
     "--alluredir=/app/allure-results", \
     "--reruns", "1", "--reruns-delay", "2", \
     "tests/"]

FROM python:3.11-slim

WORKDIR /app

# Only the pieces the mock server actually needs — keeps this image small
# and independent of Playwright's much heavier browser dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    "uvicorn[standard]==0.32.0" \
    pydantic==2.9.2 \
    pydantic-settings==2.5.2 \
    faker==30.3.0 \
    python-dotenv==1.0.1

COPY utils/ ./utils/
COPY mock_server/ ./mock_server/

EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "mock_server.main:app", "--host", "0.0.0.0", "--port", "8000"]

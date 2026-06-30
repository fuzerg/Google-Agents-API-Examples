FROM python:3.10-slim

WORKDIR /app

# Install system dependencies needed for psutil if any (slim usually has them, but good to be safe)
RUN apt-get update && apt-get install -y gcc python3-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server.py .

EXPOSE 8080

# Cloud Run overrides the PORT env var, so we must bind to it
CMD ["sh", "-c", "uvicorn mcp_server:app --host 0.0.0.0 --port ${PORT:-8080}"]

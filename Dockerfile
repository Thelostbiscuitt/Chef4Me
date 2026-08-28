FROM python:3.12-slim

WORKDIR /app

# Install system build dependencies
# gcc + rust/cargo are needed in case any package must compile from source
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    rustc \
    cargo \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip first to get better wheel resolution
RUN pip install --no-cache-dir --upgrade pip

# Install Python dependencies — prefer pre-built wheels, only build if needed
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the bot
CMD ["python", "bot.py"]

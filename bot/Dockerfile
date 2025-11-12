FROM python:3.11-slim

WORKDIR /app
COPY . .

# Install build dependencies for aiohttp
RUN apt-get update && apt-get install -y build-essential libssl-dev libffi-dev python3-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get remove -y build-essential libssl-dev libffi-dev python3-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

CMD ["python", "bot.py"]
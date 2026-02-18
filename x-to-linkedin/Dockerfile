FROM python:3.11-slim

# Dependencias del sistema para playwright y lxml
RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libatspi2.0-0 libx11-6 \
    libx11-xcb1 libxcb1 libxext6 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar y instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Chromium para playwright
RUN playwright install chromium && playwright install-deps chromium

# Copiar el código
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

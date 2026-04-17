FROM python:3.10-slim

WORKDIR /app

# Instalar dependências do sistema para o Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libnss3 \
    libxss1 \
    libasound2 \
    libgbm1 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libxrandr2 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxshmfence1 \
    fonts-unifont \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar navegadores do Playwright (Chromium) SEM as dependências de fonte problemáticas
RUN playwright install chromium
RUN playwright install-deps chromium || true

# Copiar o código do bot
COPY . .

# Comando para rodar o bot em modo live
CMD ["python", "main.py", "--live"]
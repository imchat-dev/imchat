# Temel Python imajı
FROM python:3.11-slim

# Gerekli sistem paketleri
RUN apt-get update && apt-get install -y \
    build-essential \
    libpoppler-cpp-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Çalışma dizini
WORKDIR /app

# Gereken dosyaları kopyala
COPY . /app

# Ortam değişkenleri için .env dahil
COPY .env /app/.env

# Bağımlılıkları yükle
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Port aç
EXPOSE 5010

# Uygulamayı başlat
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

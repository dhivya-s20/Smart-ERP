FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TESSERACT_CMD=/usr/bin/tesseract \
    TESSDATA_PREFIX=/app \
    OCR_LANGUAGES=eng+tam

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libstdc++6 \
        libxext6 \
        libxrender1 \
        tesseract-ocr \
        tesseract-ocr-osd \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/tessdata \
    && osd_file="$(find /usr/share/tesseract-ocr -path '*/tessdata/osd.traineddata' -print -quit)" \
    && test -n "$osd_file" \
    && cp "$osd_file" /app/tessdata/osd.traineddata

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tessdata/eng.traineddata tessdata/tam.traineddata ./tessdata/

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    PYTHONPATH=/app

WORKDIR /app

# Native speech and voice-data packages are required by the offline 30s montage.
# Do not remove licensing review: offline output remains AMBER for publication.
RUN apt-get update \
    && apt-get install -y --no-install-recommends espeak-ng espeak-ng-data \
    && rm -rf /var/lib/apt/lists/* \
    && command -v espeak-ng \
    && espeak-ng --voices >/dev/null \
    && espeak-ng -w /tmp/studio-voice-smoke.wav 'Nova Studio offline voice verification' \
    && test -s /tmp/studio-voice-smoke.wav \
    && rm /tmp/studio-voice-smoke.wav

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]

FROM python:3.11-slim

WORKDIR /app

# System deps: emoji font for Pillow story rendering
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer-cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .
RUN chmod +x entrypoint.sh

# Runtime directories (overridden by volume mounts in production)
RUN mkdir -p data logs output ready_images backgrounds

# Non-root user for security
RUN useradd --no-create-home --shell /bin/false botuser \
    && chown -R botuser:botuser /app
USER botuser

CMD ["./entrypoint.sh"]

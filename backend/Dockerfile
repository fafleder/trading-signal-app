# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.11-slim AS runner

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 1001 appuser && \
    useradd -u 1001 -g appuser -s /bin/bash -m appuser

# Copy installed packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser . .

# Create data directory
RUN mkdir -p data && chown -R appuser:appuser data

USER appuser

# Add local packages to PATH
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/app

EXPOSE 8000

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=10 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
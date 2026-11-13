FROM python:3.12-slim

WORKDIR /workspace

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/workspace

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY services/app/requirements.txt /workspace/services/app/requirements.txt
RUN pip install --no-cache-dir -r /workspace/services/app/requirements.txt

# Copy service code
COPY services/app /workspace/services/app

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /workspace
USER appuser

EXPOSE 8000

CMD ["uvicorn", "services.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

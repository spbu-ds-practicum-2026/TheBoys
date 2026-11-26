FROM python:3.12-slim
WORKDIR /workspace
COPY services/app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY services/storage /workspace/services/storage
RUN useradd -m storage && mkdir /data && chown storage /data
USER storage
CMD ["uvicorn", "services.storage.main:app", "--host", "0.0.0.0", "--port", "8000"]

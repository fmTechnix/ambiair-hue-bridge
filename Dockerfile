FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ambiair_hue_bridge.py .

VOLUME /data
ENTRYPOINT ["python", "/app/ambiair_hue_bridge.py", "-c", "/data/config.yaml"]

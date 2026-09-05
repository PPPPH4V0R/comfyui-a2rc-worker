FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir runpod

COPY handler.py /handler.py

CMD ["python", "-u", "/handler.py"]

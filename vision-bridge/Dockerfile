FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py .

ENV PYTHONBUFFERED=1

EXPOSE 11435

CMD ["python", "bridge.py"]

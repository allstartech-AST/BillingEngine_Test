FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies (prototype-only; React dashboard is not built for HF Spaces)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]

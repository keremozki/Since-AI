# Dynamis SCC: one container with the API and the built web app. Ship data is mounted, never baked in.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
# OpenCV and onnxruntime need these shared libraries at run time.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY rules/ rules/
COPY docs/rules/ docs/rules/
COPY tools/ tools/
COPY samples/ samples/
COPY --from=web /web/dist frontend/dist
# Offline by default: no AI request leaves the container unless AI_MODE=api and a key are set.
ENV AI_MODE=offline PYTHONUNBUFFERED=1
VOLUME ["/app/ship-data"]
EXPOSE 8000
WORKDIR /app/backend
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

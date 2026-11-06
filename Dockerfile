FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY data data
COPY --from=web /web/dist frontend/dist
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}

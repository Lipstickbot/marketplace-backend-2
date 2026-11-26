FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && useradd --create-home app
COPY backend/ /app/backend/
COPY agents/ /app/agents/
COPY --from=frontend /build/dist /app/frontend/dist
USER app
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "backend.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]

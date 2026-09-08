FROM node:22-slim AS frontend
WORKDIR /frontend
COPY leaderboard/frontend/package*.json ./
RUN npm ci
COPY leaderboard/frontend/ ./
RUN npm run check && npm run build

FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
COPY leaderboard/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir . -r /tmp/requirements.txt
COPY leaderboard/ leaderboard/
COPY --from=frontend /frontend/dist leaderboard/frontend/dist/
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app
ENV HOME=/home/app PYTHONUNBUFFERED=1
EXPOSE 7860
# Single publisher: do not add workers or replicas without transactional coordination.
CMD ["uvicorn", "leaderboard.app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]

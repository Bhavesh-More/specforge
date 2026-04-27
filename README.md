# SpecForge — Offline-first reasoning orchestration framework

SpecForge decomposes complex reasoning tasks into executable DAGs, executes them via local Ollama models, and self-heals failed paths using an adversarial planner/critic/resolver triad.

uvicorn src.api.main:create_app --factory --reload --port 8000



docker run -d -p 6380:6379 redis:7-alpine

docker compose -f docker/docker-compose.yml up -d
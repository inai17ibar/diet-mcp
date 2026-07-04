FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV DIET_MCP_DB_PATH=/data/diet-mcp.db
EXPOSE 8000

CMD ["diet-mcp"]

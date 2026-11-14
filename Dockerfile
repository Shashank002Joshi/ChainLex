FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["chainlex-api", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY stealth_flash_qa.py config.example.json /app/
RUN python -m pip install --no-cache-dir .

CMD ["flash-sale-qa", "--config", "config.json"]

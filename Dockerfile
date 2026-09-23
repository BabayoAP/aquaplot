FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Assessments default to the working directory; a mounted volume overrides it
# through RIFFLE_DB (see render.yaml).
ENV RIFFLE_DB=/app/riffle.db

EXPOSE 8000
CMD ["uvicorn", "riffle.app:app", "--host", "0.0.0.0", "--port", "8000"]

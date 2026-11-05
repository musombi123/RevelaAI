FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pandas polars numpy scipy sympy statsmodels matplotlib plotly scikit-learn duckdb qiskit qutip openpyxl python-docx python-pptx
RUN useradd --uid 65532 --no-create-home --shell /usr/sbin/nologin worker
USER 65532:65532
WORKDIR /tmp

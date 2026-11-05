FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends docker.io ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py /srv/app.py
RUN useradd --uid 10001 --create-home sandboxapi
USER 10001
EXPOSE 8080
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080","--workers","1"]

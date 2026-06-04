FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        nodejs npm git tmux && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ainrf

# Install Python package
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir .

# Build frontend
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci
COPY frontend/ frontend/
RUN cd frontend && npm run build && \
    mkdir -p /opt/ainrf/frontend-dist && \
    cp -r dist /opt/ainrf/frontend-dist/

# State directory
RUN mkdir -p /opt/ainrf/state
VOLUME /opt/ainrf/state

EXPOSE 8000

ENV AINRF_PRODUCTION=1
ENV AINRF_HOST=0.0.0.0
ENV AINRF_PORT=8000

CMD ["python", "-m", "ainrf", "serve", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--state-root", "/opt/ainrf/state"]

ARG BUILD_ARCH=amd64

# Build the Vue app in the Supervisor's local app/ context; Node stays out of runtime.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.13-alpine3.22

RUN apk add --no-cache ffmpeg \
    && pip install --no-cache-dir \
        "fastapi==0.115.14" \
        "uvicorn[standard]==0.32.1" \
        "httpx==0.28.1" \
        "pydantic==2.11.7" \
        "python-multipart==0.0.20"

COPY src /opt/cinema-studio/src
COPY --from=ui /ui/dist /opt/cinema-studio/src/cinema_studio/static/ui
COPY rootfs /

ENV PYTHONPATH=/opt/cinema-studio/src
RUN chmod 0755 /usr/bin/cinema-studio

CMD ["/usr/bin/cinema-studio"]

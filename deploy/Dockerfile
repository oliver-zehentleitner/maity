# The Maity hub: API and static dashboard in one process.
# Build from the repository root: docker build -f deploy/Dockerfile .

FROM python:3.12-slim AS build
WORKDIR /src
COPY hub/ hub/
RUN pip wheel --no-cache-dir --wheel-dir /wheels ./hub

FROM python:3.12-slim
RUN useradd --system --uid 10001 --home-dir /app maity
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
# web/ is optional until the dashboard exists; Dockerfile.dockerignore keeps the
# context to hub/ and web/, so this copies the dashboard or nothing.
COPY . /tmp/context/
RUN mkdir -p /app/web && if [ -d /tmp/context/web ]; then cp -r /tmp/context/web/. /app/web/; fi \
    && rm -rf /tmp/context
USER maity
ENV MAITY_BIND=0.0.0.0:8080 \
    MAITY_WEB_DIR=/app/web
EXPOSE 8080
ENTRYPOINT ["maity-hub"]
CMD ["serve"]

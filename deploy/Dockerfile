# The Maity hub: API and static dashboard in one process.
# Build from the repository root: docker build -f deploy/Dockerfile .
#
# Without MAITY_DATABASE_URL the hub uses SQLite in /app/data, a volume owned
# by the hub's user; `docker run -v maity-data:/app/data <image> migrate`
# prepares it. For PostgreSQL or MySQL/MariaDB set MAITY_DATABASE_URL.

FROM python:3.12-slim AS build
WORKDIR /src
# Dockerfile.dockerignore limits the context to hub/ and web/, without dotfiles.
COPY . .
RUN pip wheel --no-cache-dir --wheel-dir /wheels ./hub && mkdir -p web

FROM python:3.12-slim
RUN useradd --system --uid 10001 --home-dir /app maity \
    && mkdir -p /app/data && chown maity /app/data
WORKDIR /app
# Installed from the build stage through a bind mount, so no layer keeps the wheels.
RUN --mount=type=bind,from=build,source=/wheels,target=/wheels \
    pip install --no-cache-dir /wheels/*.whl
COPY --from=build /src/web /app/web
USER maity
ENV MAITY_BIND=0.0.0.0:8080 \
    MAITY_DATABASE_URL=sqlite:////app/data/maity-hub.db \
    MAITY_WEB_DIR=/app/web
VOLUME /app/data
EXPOSE 8080
ENTRYPOINT ["maity-hub"]
CMD ["serve"]

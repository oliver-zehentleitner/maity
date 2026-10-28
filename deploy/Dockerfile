# The Maity hub: API and static dashboard in one process.
# Build from the repository root: docker build -f deploy/Dockerfile .
#
# Without MAITY_DATABASE_URL the hub uses SQLite in /app/data, a volume owned
# by the hub's user; `docker run -v maity-data:/app/data <image> migrate`
# prepares it. For PostgreSQL or MySQL/MariaDB set MAITY_DATABASE_URL.

# The base by digest, so a rebuild of the same commit gets the same layers. To
# move it: docker buildx imagetools inspect python:3.12-slim, then both lines.
FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2 AS build
WORKDIR /src
# Dockerfile.dockerignore limits the context to hub/ and web/, without dotfiles.
COPY . .
# The wheel is built with the pinned backend (hub/requirements/build.txt), not
# whatever hatchling is newest; every download is checked against its hash.
RUN pip install --no-cache-dir --require-hashes -r hub/requirements/build.txt \
    && pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir /wheels ./hub \
    && cp hub/requirements/runtime.txt /wheels/ && mkdir -p web

FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
RUN useradd --system --uid 10001 --home-dir /app maity \
    && mkdir -p /app/data && chown maity /app/data
WORKDIR /app
# The dependencies exactly as CI tested them (hub/requirements/runtime.txt,
# with hashes), then the hub itself without resolving anything again. Both
# come from the build stage through a bind mount, so no layer keeps them.
RUN --mount=type=bind,from=build,source=/wheels,target=/wheels \
    pip install --no-cache-dir --require-hashes -r /wheels/runtime.txt \
    && pip install --no-cache-dir --no-deps /wheels/*.whl
COPY --from=build /src/web /app/web
USER maity
# MALLOC_ARENA_MAX: glibc gives each busy thread its own memory arena, and the hub's request
# threads fragment them: under a mixed load the process grew by 1 KiB a request and, with two
# arenas, not at all (hub/context/packaging.md).
ENV MAITY_BIND=0.0.0.0:8080 \
    MAITY_DATABASE_URL=sqlite:////app/data/maity-hub.db \
    MAITY_WEB_DIR=/app/web \
    MALLOC_ARENA_MAX=2
VOLUME /app/data
EXPOSE 8080
ENTRYPOINT ["maity-hub"]
CMD ["serve"]

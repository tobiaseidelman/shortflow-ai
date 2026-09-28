FROM node:22-bookworm-slim AS javascript
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
RUN node --version

# This Python app does not use Yarn. Its inherited apt source has an expired key.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg zstd fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && python -c 'import sys; assert sys.version_info[:2] == (3, 12)' \
    && ffmpeg -version

# Local inference only. Model weights are downloaded on first story generation,
# into the persistent workspace storage, not into the image or Git.
RUN curl -fsSL --retry 3 https://ollama.com/install.sh -o /tmp/install-ollama.sh \
    && sh /tmp/install-ollama.sh \
    && rm /tmp/install-ollama.sh
ENV OLLAMA_NO_CLOUD=1

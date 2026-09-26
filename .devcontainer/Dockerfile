FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# This Python app does not use Yarn. Its inherited apt source has an expired key.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && python -c 'import sys; assert sys.version_info[:2] == (3, 12)' \
    && ffmpeg -version

FROM node:20-bookworm

# Install Python 3.11 + pip (for FastAPI/Celery) and system deps (git, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    libsecret-1-0 \
    libsecret-tools \
    dbus \
    gnome-keyring \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Playwright (Node) deps. This installs browser binaries + OS deps at build time.
# Note: This increases image size; for CI you may prefer prebuilt Playwright images.
RUN npx -y playwright@1.57.0 install --with-deps

COPY app /app/app

# Use existing 'node' user (uid 1000) for Claude Code (it refuses to run as root with --dangerously-skip-permissions)
RUN chown -R node:node /app && \
    mkdir -p /home/node/.npm && \
    chown -R node:node /home/node/.npm

# Switch to non-root user
USER node

EXPOSE 8000

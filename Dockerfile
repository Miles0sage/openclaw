FROM node:22-bookworm

# Install system dependencies for native modules (sharp, node-gyp, etc)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    make \
    g++ \
    ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Bun (required for build scripts)
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/root/.bun/bin:${PATH}"

RUN corepack enable

WORKDIR /app

# Support concurrency tuning for 7GB GitHub Actions runners
ARG PNPM_CONCURRENCY=16
ARG OPENCLAW_DOCKER_APT_PACKAGES=""
RUN if [ -n "$OPENCLAW_DOCKER_APT_PACKAGES" ]; then \
      apt-get update && \
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $OPENCLAW_DOCKER_APT_PACKAGES && \
      apt-get clean && \
      rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*; \
    fi

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY ui/package.json ./ui/package.json
COPY patches ./patches
COPY scripts ./scripts

# Install dependencies (use --child-concurrency for 7GB-constrained environments)
RUN if [ "${PNPM_CONCURRENCY}" -lt 4 ]; then \
      echo "🔧 Installing with --child-concurrency=1 for low-memory environment..." && \
      pnpm install --frozen-lockfile --child-concurrency=1; \
    else \
      pnpm install --frozen-lockfile; \
    fi

COPY . .

# Support two build modes:
# 1. Full build (default): pnpm build generates dist/
# 2. Pre-built mode: skip build if dist/ already exists (from GitHub Actions artifacts)
RUN if [ ! -d dist ] || [ -z "$(ls -A dist)" ]; then \
      echo "🔨 Building from source (workspace-concurrency=${PNPM_CONCURRENCY})..." && \
      pnpm build --workspace-concurrency=${PNPM_CONCURRENCY} && \
      export OPENCLAW_PREFER_PNPM=1 && \
      pnpm ui:build; \
    else \
      echo "✅ Using pre-built dist/ artifacts (from GitHub Actions)"; \
    fi

ENV NODE_ENV=production

# Allow non-root user to write temp files during runtime/tests.
RUN chown -R node:node /app

# Security hardening: Run as non-root user
# The node:22-bookworm image includes a 'node' user (uid 1000)
# This reduces the attack surface by preventing container escape via root privileges
USER node

# Start gateway server with default config.
# Binds to loopback (127.0.0.1) by default for security.
#
# For container platforms requiring external health checks:
#   1. Set OPENCLAW_GATEWAY_TOKEN or OPENCLAW_GATEWAY_PASSWORD env var
#   2. Override CMD: ["node","dist/index.js","gateway","--allow-unconfigured","--bind","lan"]
CMD ["node", "dist/index.js", "gateway", "--allow-unconfigured"]

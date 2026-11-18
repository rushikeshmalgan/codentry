# Container image for services/ai-review (FastAPI + the ESLint/Semgrep analysis layer).
#
# Why a Dockerfile at all: ESLint needs Node.js and Semgrep needs Python, and Render's
# native Python runtime is not confirmed to ship Node (docs/deployment.md). One image
# that contains both removes that unknown, and it is also the "throwaway container,
# unprivileged user" that docs/architecture.md gap #2 asks for.
#
# Build context is services/ai-review (see render.yaml `dockerContext`).
#
#   docker build -t codentry-ai-review .                      # production image (last stage)
#   docker build --target test -t codentry-ai-review:test .   # image that can run pytest
#
# This is NOT a sandbox for hostile pull requests: the analysis subprocesses still run
# in the same container as the service. It narrows the blast radius (non-root user,
# read-only application tree, no build tooling in the runtime image); it does not
# provide seccomp or a network namespace.

# ---- Stage 1: install the pinned ESLint baseline with npm (build-time only) ------------
FROM node:22-bookworm-slim AS eslint-deps
WORKDIR /build
COPY analysis/eslint-baseline/package.json analysis/eslint-baseline/package-lock.json ./
# `npm ci` installs exactly what package-lock.json pins and fails if it is out of sync.
RUN npm ci --omit=dev --no-audit --no-fund

# ---- Stage 2: Python + the `node` binary + application code ------------------------------
FROM python:3.13-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:${PATH}"

# Only the `node` executable is copied: ESLint is launched as `node <eslint>/bin/eslint.js`
# (analysis/eslint_runner.py), so npm and the rest of the Node toolchain are not needed at
# runtime.
COPY --from=eslint-deps /usr/local/bin/node /usr/local/bin/node

RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin codentry \
    && python -m venv /opt/venv

WORKDIR /app

COPY requirements.txt ./
# Semgrep is found next to the interpreter (analysis/semgrep_runner.py::_find_semgrep), so it
# must live in the same virtualenv the service runs from.
RUN pip install -r requirements.txt

COPY app ./app
COPY analysis ./analysis
COPY --from=eslint-deps /build/node_modules ./analysis/eslint-baseline/node_modules

# The service user has no home directory. Tools launched by the service get their own
# throwaway HOME (analysis/subprocess_env.py); this only keeps manual `docker run ... semgrep`
# commands from crashing on a missing ~/.semgrep.
ENV HOME=/tmp

# Application files stay root-owned and read-only to the service user.
USER codentry

# ---- Stage 3: test image (adds dev dependencies and the test suite) ----------------------
FROM base AS test
USER root
COPY requirements-dev.txt pyproject.toml ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests
# Operator scripts (e.g. scripts/track_g_check.py) have unit tests too; they are not
# part of the production image.
COPY scripts ./scripts
USER codentry
# -p no:cacheprovider: /app is not writable by the service user.
# One test is deselected on purpose: test_scope_guards.py::test_evaluation_harness_depends_on_
# the_analysis_layer_only inspects the repository's top-level evaluation/ directory, which is
# outside this image's build context (services/ai-review), so here it can only fail by
# finding nothing. It still runs on the host and in CI, where the whole repository exists.
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider", "-q", \
     "--deselect", "tests/test_scope_guards.py::test_evaluation_harness_depends_on_the_analysis_layer_only"]

# ---- Stage 4: production image (must stay the LAST stage: it is the default target) -----
FROM base AS runtime
ENV ENVIRONMENT=production
EXPOSE 10000
# Render injects $PORT; 10000 is Render's documented default for local runs.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]

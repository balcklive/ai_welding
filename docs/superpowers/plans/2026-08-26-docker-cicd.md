# Docker CI/CD 自动部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use supo-subagent-driven-development (recommended) or supo-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a production-oriented Docker image and SSH-driven GitHub Actions deployment for the full-stack application.

**Architecture:** A multi-stage Dockerfile builds the Vite frontend with Node 20, then packages it into a Python 3.12-slim FastAPI image. GitHub Actions validates both stacks and SSHes to the host, where `git pull`, `docker build`, and `docker run --env-file .env` replace the application container and verify `/api/v1/health`.

**Tech Stack:** GitHub Actions, appleboy/ssh-action, Docker, Node 20, Python 3.12, uv, FastAPI/Uvicorn.

## Global Constraints

- Never commit `.env`, passwords, private keys, or tokens.
- Python dependency operations use `uv`; backend runtime uses `uvicorn`.
- Deployment uses direct `docker build` and `docker run`, not PM2 or Compose.
- The server-side `.env` remains on the server and is passed with `--env-file .env`.
- Existing GitHub Pages workflow remains unchanged.

---

### Task 1: Container image definition

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Modify: `CLAUDE.md` (deployment files note)

- [x] Add a Node 20 builder stage that runs `npm ci` and `npm run build`.
- [x] Add a Python 3.12-slim runtime stage, install `backend/pyproject.toml` dependencies with uv, copy backend code and frontend `dist/`, expose port 8000, and run Uvicorn on `0.0.0.0:8000`.
- [x] Exclude Git metadata, local dependencies, env files, logs, and build caches from the Docker context.
- [ ] Run `docker build -t ai-welding:test .` and verify it completes (blocked: current environment cannot access Docker daemon).

### Task 2: CI/CD workflow

**Files:**
- Create: `.github/workflows/deploy-docker.yml`
- Modify: `.github/workflows/CLAUDE.md`

- [x] Configure `push` to `main` and `workflow_dispatch`.
- [x] Add CI steps for Node 20 (`npm ci`, lint, typecheck, build) and backend Python 3.12 with uv (`uv sync --locked`, `uv run pytest`).
- [x] After CI succeeds, use `appleboy/ssh-action@v1.2.2` with `SSH_HOST`, `SSH_PORT`, `SSH_USER`, and `SSH_PRIVATE_KEY`.
- [x] In the SSH script, run `git pull --ff-only origin main`, build a timestamped image, stop/remove the named container, then run the container with `--env-file .env`, `--restart unless-stopped`, and configurable host port (default host port `8223`, default path `/home/wwwroot/code/ai_welding`).
- [x] Verify `http://127.0.0.1:8000/api/v1/health` with curl and print container logs on failure.
- [x] Run YAML/static checks and inspect the resulting diff.

### Task 3: Verification

**Files:**
- No new files.

- [x] Run `npm run lint`.
- [x] Run `npm run typecheck`.
- [x] Run `npm run build`.
- [ ] Run `cd backend && uv sync --locked && uv run pytest` (blocked by pre-existing failure in `test_create_registration_rejects_concurrent_duplicate_payload`; full run also exceeds the local timeout).
- [x] Confirm `git diff --check` passes and no secret material is present in new files.

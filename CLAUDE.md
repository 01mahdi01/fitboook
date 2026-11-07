# video_application (fitboook)

Django/DRF backend for `api.fitboook.ir`. Repo: `git@github.com:01mahdi01/fitboook.git` (branch `main`).

## Deployment

Production: `ubuntu@45.135.242.163`, project at `/home/ubuntu/video_application` (a git checkout of `main`).
Stack: `docker-compose.prod.yml` (nginx, web/gunicorn, celery worker, postgres, redis, minio, certbot).

**Deploy = one command from your machine:**

```bash
scripts/deploy-remote.sh
```

It refuses to run with uncommitted changes or off `main`, then:
1. `git push origin main`
2. `ssh -A` into the server and runs `scripts/deploy.sh` there, which:
   - `git pull --ff-only`
   - rebuilds `web` + `worker` images (new requirements get installed here)
   - `up -d` — migrations + collectstatic run automatically via `scripts/entrypoint.sh`
   - on docker-compose v1's `KeyError: 'ContainerConfig'` (old containers left stopped as
     `<hash>_video_application_*`, site down), removes those and retries
3. Polls `https://api.fitboook.ir/api/schema/` until 200 (~1 min max).

Overrides: `DEPLOY_SERVER`, `DEPLOY_DIR`, `HEALTH_URL` env vars.

**Rules**
- Never edit files on the server — commit locally and deploy, or the server drifts from the repo.
- The server has **no GitHub key**: `git pull` works only via `ssh -A` (your local key is forwarded,
  never copied). Deliberate — a key on the server would expose the whole GitHub account if it's breached.
- Secrets live only in the server's `.env` (git-ignored). New env vars: add them to `.env.prod.example`
  in the repo **and** by hand to the server's `.env` before deploying.
- `deploy.sh` does not `pull` third-party images, so `minio:latest` etc. are not upgraded silently.
- Docker on the server needs `sudo` (the scripts handle it).

**Rollback:** `git revert <sha> && scripts/deploy-remote.sh`.

**Logs:** `ssh ubuntu@45.135.242.163 'cd video_application && sudo docker-compose -f docker-compose.prod.yml logs --tail 100 web'`

First-time TLS setup: `scripts/init-letsencrypt.sh` (on the server).

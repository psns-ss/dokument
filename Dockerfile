FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# No code is copied into the image — docker-compose.yml bind-mounts `app/`,
# `templates/` and `logic/` over /app, so an edit on the host is live after a
# process restart and nothing stale can hide in the image. The mounts are
# therefore required: without them this image has dependencies and no application.
# `.dockerignore` stays as insurance for whoever adds a COPY back later.

EXPOSE 5000

# Gunicorn: sync workers + threads (thread-local state in context_manager/loader
# needs real threads — no gevent/eventlet). One SECRET_KEY per boot, shared by
# all workers: flask-session signs the session cookie with it, so per-worker
# random keys would invalidate sessions on cross-worker requests. /tmp sessions
# don't survive restarts, so a per-boot key matches the old per-boot semantics.
# --timeout 120: long doc renders must not be killed at the 30 s default.
# Access log goes to the app log file: one chronological log (request lines +
# app lines), which the E2E log tests also assert against. Boot/worker errors
# stay on stderr -> docker logs.
CMD ["sh", "-c", "export SECRET_KEY=$(openssl rand -hex 32) && exec gunicorn --workers 2 --threads 4 --timeout 120 --access-logfile /app/flask_app.log -b 0.0.0.0:5000 generator:app"]

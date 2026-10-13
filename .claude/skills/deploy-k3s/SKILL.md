---
name: deploy-k3s
description: Build and deploy aicafe (backend, frontend, Postgres) to the k3s cluster with kubectl context `charles-k3s` and namespace `aicafe`, using kustomize, a diff the user reviews, and a smoke test. Use when the user asks to deploy, release, roll out, or update aicafe on k3s.
disable-model-invocation: true
argument-hint: "[image-tag]"
---

# Deploy aicafe to k3s

The cluster is shared (the same kubeconfig also holds EKS dev/prod contexts). Everything here is pinned to
**context `charles-k3s`, namespace `aicafe`**; `scripts/deploy.sh` refuses anything else. Never run `kubectl`
for this project without `--context charles-k3s -n aicafe`.

Never apply without the user approving the diff of that specific change in this conversation. Changes outside
the `aicafe` namespace (e.g. the Traefik Service in `kube-system`) need their own explicit approval.

## What gets deployed
`deploy/k8s/base`: Postgres + pgvector (StatefulSet), `aicafe-backend` (migrations run in an init container),
`aicafe-frontend` (nginx, proxies `/api`), Ingress `rcafe.koh.it.kr` on the Traefik class (HTTP only).
`deploy/k8s/overlays/prod` pins the image names/tags. One-off jobs (seed, taste, crawl) live in
`deploy/k8s/jobs/job.yaml`. `aicafe-collector` (`base/collector.yaml`) is a CronJob at 03:30 KST that collects the
areas visitors requested (`collect-requests`, 150 minute budget); check it with
`kubectl --context charles-k3s -n aicafe get cronjob,job` and read a run with `logs job/<name>`. The admin page's
"run now" creates Jobs named `aicafe-collect-now-*` through the `aicafe-api` ServiceAccount
(`base/admin-rbac.yaml`: create Jobs, read that CronJob, list pods, nothing more). To try it by hand:
`kubectl --context charles-k3s -n aicafe create job --from=cronjob/aicafe-collector test-collect` (delete it after).

## Workflow
1. **Preflight**: `scripts/deploy.sh check` (context, namespace, node architecture, DNS for the host,
   whether a Traefik Service exists).
2. **Secrets** (first deploy only; created out of band, values never printed or committed):
   - `aicafe-db`: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
   - `aicafe-backend`: `AICAFE_DATABASE_URL` (same credentials), `AICAFE_KMA_AUTH_KEY`, and for the admin page
     `AICAFE_ADMIN_USER`, `AICAFE_ADMIN_PASSWORD`, `AICAFE_ADMIN_SESSION_KEY`
   `scripts/deploy.sh secrets` creates them if missing: it generates the DB password and reads the KMA key
   from the `AICAFE_KMA_AUTH_KEY` environment variable, and adds the admin keys (random values) when absent.
   It prints key names only. The operator reads the login with
   `kubectl --context charles-k3s -n aicafe get secret aicafe-backend -o jsonpath='{.data.AICAFE_ADMIN_PASSWORD}' | base64 -d`.
   Never type the admin password into the live site on someone's behalf.
3. **Build and push** images for the node's architecture (`linux/amd64`) to the plain-HTTP registry that already
   runs on the k3s server, `121.143.126.21:5000` (the same one the `chf` app uses; no pull secret needed):
   `scripts/deploy.sh build <tag>`. A buildx `docker-container` builder pushes with `registry.insecure=true`, so
   the local Docker daemon settings stay untouched. Override with `IMAGE_PREFIX` if the registry moves.
4. **Diff**: `scripts/deploy.sh diff <tag>`; show the user what changes and ask for approval.
5. **Apply**: `scripts/deploy.sh apply <tag> --yes`, then wait for the rollouts.
6. **Data**: load the collected data into an empty database (`scripts/deploy.sh load-data <dump.sql.gz>`) or swap it
   atomically (`... --replace`, one transaction). `backend/scripts/export_data.sh` prepares the dump.
7. **Smoke test**: `scripts/deploy.sh smoke` calls the API through the Service and, if DNS is ready,
   through `http://rcafe.koh.it.kr`.

## Rollback
`kubectl --context charles-k3s -n aicafe rollout undo deployment/aicafe-backend` (or `-frontend`).
Database migrations are additive; do not downgrade without asking.

---
name: deploy-frontend
description: Build a React frontend and deploy it as a static site to a private S3 bucket behind CloudFront (Origin Access Control), then invalidate the CloudFront cache. Use when the user asks to deploy, release, or publish a frontend to an environment (dev, staging, prod). Supports projects with multiple frontends.
disable-model-invocation: true
argument-hint: "[frontend-dir] [env]"
---

# Deploy frontend to S3 + CloudFront

Deploys go to real infrastructure. Never run the actual deploy (`--yes`) without the user's
explicit approval of the plan in this conversation, for every frontend and every environment.

## Deployment model
- Static build uploaded to S3, served through CloudFront.
- The bucket is private: CloudFront reads it via Origin Access Control (OAC); no public bucket policy.
- CloudFront is invalidated (`/*`) after every deploy.
- Environment config (API base URL, etc.) comes from build-time env vars per environment, kept in
  `<frontend-dir>/.deploy/<env>.env`, never hardcoded in source.

## Workflow

1. **Pick the frontend.** Arguments: `$ARGUMENTS`. If no directory was given, find candidates
   (directories with a `package.json` and a `.deploy/` folder, or matching `frontend`, `frontends/*`,
   `*-frontend`, `frontend-*`). If more than one fits and the user did not say which, ask.
   If the user asks to deploy several frontends, handle them one at a time with a separate plan each.

2. **Pick the environment.** If not given, list the `.deploy/*.env` files and ask. Do not default to prod.

3. **Make sure the config exists.** If `<frontend-dir>/.deploy/<env>.env` is missing, create it from
   [assets/deploy.env.example](assets/deploy.env.example). Ask the user for the bucket name, distribution
   ID, and AWS profile; do not guess them.

4. **Run checks and show the plan** (builds and uploads nothing):
   ```bash
   bash .claude/skills/deploy-frontend/scripts/deploy.sh <frontend-dir> <env>
   ```
   The script checks credentials, the expected account (`AWS_ACCOUNT_ID`), that the bucket is private,
   and that the CloudFront S3 origin uses OAC. If a check fails, stop and report it. Do not change bucket
   policies, Block Public Access, OAC, or distribution settings from this skill; that is an infrastructure
   change for the user to make.

5. **Optional preview:** `--dry-run` builds and lists what S3 sync would change. Offer it for prod.

6. **Get approval.** Show the plan (account, bucket, distribution, domain, environment) and wait for a
   clear yes.

7. **Deploy:**
   ```bash
   bash .claude/skills/deploy-frontend/scripts/deploy.sh <frontend-dir> <env> --yes [--wait]
   ```

8. **Report** the CloudFront URL and the invalidation ID. If something failed, show the error output
   as-is.

## Caching behaviour
- Hashed asset directory (`assets/` for Vite, `static/` for CRA, or `HASHED_ASSETS_DIR`):
  `max-age=31536000, immutable`, uploaded first, old files kept so open tabs keep working.
- Everything else (`index.html`, `favicon`, ...): `no-cache`, synced with `--delete`.

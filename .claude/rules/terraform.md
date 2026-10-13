---
paths:
  - "**/*.tf"
  - "**/*.tfvars"
  - "**/*.tftest.hcl"
---

# Terraform

Based on terraform-best-practices.com. Deploy (plan/apply) is done only through the `terraform-deploy`
skill; new modules/compositions are created with the `terraform-scaffold` skill.

## Building blocks
- **Resource module**: a small reusable group of resources doing one job (e.g. `static-site`: S3 + CloudFront + OAC).
  No `provider` or `backend` blocks; only `required_providers` in `versions.tf`.
- **Infrastructure module**: combines resource modules for one purpose within one region/account.
- **Composition**: the root module you run `plan`/`apply` in, for one environment and one component. Owns the
  `provider`, `backend`, and `terraform.tfvars`. One composition = one state.

## Layout
Several services (backends, frontends) share one infra tree. Follow the existing layout if the repo already
has one; otherwise:

```
infra/
  modules/<module-name>/        # internal resource/infrastructure modules
  envs/<env>/<component>/       # compositions, e.g. envs/prod/network, envs/prod/order-backend, envs/prod/web-frontend
```

- Each environment runs in its own AWS account and its own state. Environments never share resources.
- Split compositions by component and lifecycle (network, data, each service) to keep plans fast and limit
  blast radius. Do not put unrelated resources in the same composition.
- Files per module/composition: `main.tf` (resources, module calls, locals, data sources), `variables.tf`,
  `outputs.tf`, `versions.tf`; compositions also have `providers.tf`, `backend.tf`, `terraform.tfvars`.
- `terraform.tfvars` exists only in compositions, never in modules.
- Pass values between compositions through outputs + `terraform_remote_state` (or SSM parameters);
  never hardcode IDs/ARNs that another composition owns.

## State and versions
- Remote state only: S3 backend with `encrypt = true` and `use_lockfile = true`; key `<env>/<component>/terraform.tfstate`.
- Never commit `*.tfstate`, `*.tfplan`, or `.terraform/`. Do commit `.terraform.lock.hcl`.
- Pin `required_version` and every provider (`~>`) in `versions.tf`. Pin external module versions
  (`version = "x.y.z"` or `?ref=vX.Y.Z`); local modules use relative paths.
- Providers are configured only in compositions. Set `allowed_account_ids` so a wrong AWS profile fails
  instead of changing the wrong account, and set `default_tags` (`Environment`, `Component`, `ManagedBy = "terraform"`).

## Naming
- Terraform identifiers: lowercase `snake_case`. Human-facing values (resource `name`, DNS, tags) use dashes.
- Do not repeat the type in the name: `aws_route_table.public`, not `aws_route_table.public_route_table`.
- Use `this` for the only resource of its type in a module; otherwise use descriptive singular names.
- Argument order in a block: `count`/`for_each` first, then arguments, then `tags`, then `depends_on`, then `lifecycle`.
- Conditions in `count`/`for_each` use booleans (`var.logging_enabled ? 1 : 0`), not `length(...)` tricks.
- Prefer `for_each` over `count` for collections so removing one item does not shift the others.

## Variables and outputs
- Every variable and output has a `description`. Every variable has a `type`.
- Plural names for lists/maps. Positive booleans: `encryption_enabled`, not `encryption_disabled`.
- Prefer simple types; use `object({...})` with `optional()` defaults only when structure must be enforced.
- `nullable = false` for values that must never be null. Add `validation` blocks for enums, CIDRs, name formats.
- Output names follow `{name}_{type}_{attribute}`, dropping `this` (e.g. `aws_s3_bucket.this.id` → `s3_bucket_id`).
  Use `try()` instead of `element(concat(...))`.

## Secrets
- Never put secrets in `.tf`, `.tfvars`, or outputs. Read them at runtime (Secrets Manager / SSM data sources)
  or let the service manage them (e.g. `manage_master_user_password` for RDS).
- Use write-only arguments (`*_wo`) where available so secrets never reach state.

## Style
- `terraform fmt` is the formatter (the quality-gate hook runs it on every edit). Comments use `#` only.
- Refactors that rename or move resources use `moved {}` blocks, not `terraform state mv`.
- Every module has a `README.md` describing inputs, outputs, and an example call.

## Safety for Claude
- Do not run `terraform apply`, `destroy`, `import`, `state *`, `force-unlock`, `taint`, or `-auto-approve`
  directly. Applying goes through the `terraform-deploy` skill; anything touching state needs explicit user
  approval for that specific command.
- `fmt`, `validate`, `init -backend=false`, and reading code are always fine.
- Changes that destroy or replace stateful resources (databases, buckets with data, state buckets, KMS keys)
  must be called out explicitly before planning; add `lifecycle { prevent_destroy = true }` to such resources.

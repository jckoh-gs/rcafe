---
name: terraform-scaffold
description: Create Terraform building blocks that follow the project's Terraform rules - the infra root (tflint, gitignore, editorconfig), a new composition for an environment + component (one state), a new reusable module, or a static-site (S3 + CloudFront OAC) setup for a frontend. Use when the user wants to add infrastructure for a new service, environment, or module.
argument-hint: "[root | composition <env> <component> | module <name> | static-site <env> <frontend>]"
---

# Terraform scaffold

Templates are in `assets/`. Placeholders look like `__NAME__`; replace every one, and run `terraform fmt`
afterwards. Follow the existing layout if the repo already has one; the default is:

```
infra/
  .tflint.hcl  .gitignore  .editorconfig
  modules/<module-name>/
  envs/<env>/<component>/
```

## root: set up the infra directory (once per repo)
Copy `assets/infra-root/{.tflint.hcl,.gitignore,.editorconfig}` into `infra/`. Merge
`assets/infra-root/.pre-commit-config.yaml` into the repo root's pre-commit config only if the team uses
pre-commit (ask).

## composition <env> <component>
1. Ask for anything you cannot find in existing compositions: AWS account ID, region, state bucket and
   its region. Never invent account IDs or bucket names.
2. Copy `assets/composition/*` to `infra/envs/<env>/<component>/` and replace `__ENV__`, `__COMPONENT__`,
   `__REGION__`, `__AWS_ACCOUNT_ID__`, `__STATE_BUCKET__`, `__STATE_REGION__`.
3. Add module calls in `main.tf` and expose what other compositions or deploy tooling need in `outputs.tf`.
4. The state bucket must already exist. If it does not, tell the user; do not create it from this composition.

## module <name>
Copy `assets/module/*` to `infra/modules/<name>/` (`__MODULE__` = name, `__MODULE_SNAKE__` = snake_case).
Keep it provider-free; only `required_providers` with a lower bound (`>=`). Fill in README inputs/outputs.

## static-site <env> <frontend>
For a frontend deployed by the `deploy-frontend` skill.
1. Copy `assets/modules/static-site/` to `infra/modules/static-site/` if it is not there yet.
2. Create the composition `infra/envs/<env>/<frontend>/` as above and call the module:
   ```hcl
   module "static_site" {
     source = "../../../modules/static-site"

     bucket_name = "${var.environment}-<frontend>-${var.aws_account_id}"
   }
   ```
3. Output `s3_bucket_id` and `cloudfront_distribution_id`. After it is applied (via `terraform-deploy`),
   their values go into `<frontend>/.deploy/<env>.env` as `S3_BUCKET` and `CLOUDFRONT_DISTRIBUTION_ID`.

## Finish
Run `terraform fmt -recursive` and, in each new directory, `terraform init -backend=false && terraform validate`.
Do not plan or apply here; that is the `terraform-deploy` skill.

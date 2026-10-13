---
name: terraform-deploy
description: Plan and apply Terraform changes for one composition (one environment + component, one state), using a saved plan that the user reviews before anything changes in the cloud. Use when the user asks to deploy, provision, or apply infrastructure for a service or environment.
disable-model-invocation: true
argument-hint: "[composition-dir | <env> <component>]"
---

# Terraform deploy (plan → review → apply)

`apply` changes real infrastructure. Never apply without the user approving that specific plan in this
conversation. Approval of one plan does not carry over to another composition, a re-plan, or another env.

## Workflow

1. **Find the composition.** Arguments: `$ARGUMENTS`. Compositions are directories with a `backend` block,
   usually `infra/envs/<env>/<component>/`. Resolve `<env> <component>` to that path. If it is ambiguous or
   missing, list the compositions and ask. Do not default to prod.

2. **Several compositions?** Handle one at a time, in dependency order (a composition that reads another's
   `terraform_remote_state` goes after it, e.g. network → data → services). For prod, if the same change
   exists for a lower environment that has not been applied yet, suggest applying there first.

3. **Plan** (changes nothing in the cloud):
   ```bash
   bash .claude/skills/terraform-deploy/scripts/tf.sh <composition-dir> plan
   ```
   The script refuses local state, then runs init, `fmt -check`, `validate`, tflint, and saves the plan.
   If it fails, fix code problems (fmt/validate/tflint) and plan again. Credential, backend, or lock errors
   go back to the user. Never `force-unlock` on your own.

4. **Review it with the user.** Read the full plan text the script points to, then show:
   - which AWS identity/account and composition this is,
   - the change counts,
   - every DESTROY / REPLACE line verbatim, plus a short note on what each resource is and whether it holds
     data (databases, buckets, volumes, KMS keys, state buckets),
   - notable in-place updates (security groups, IAM, DNS, scaling).

   Point out anything the user did not ask for (drift, unexpected replacements). If there are destructive
   changes, the user must explicitly accept them, not just say "go".

5. **Apply** only after a clear yes for this plan:
   ```bash
   bash .claude/skills/terraform-deploy/scripts/tf.sh <composition-dir> apply --yes
   ```
   This applies exactly the saved plan. If it is older than 60 minutes or the state changed, plan again and
   ask again. If the user declines, run `discard`.

6. **Report** the result and outputs. If the composition hosts a frontend (`static-site` module), offer to set
   `S3_BUCKET` / `CLOUDFRONT_DISTRIBUTION_ID` in that frontend's `.deploy/<env>.env` for `deploy-frontend`.

## Never
- `terraform apply` without a saved plan, `-auto-approve`, `destroy`, `-target`, `-replace`, `import`,
  `state` subcommands, `force-unlock`, or `taint`, unless the user asks for that exact command.
- Editing state files, or changing the backend configuration, to get a plan through.
- Loosening `prevent_destroy`, `allowed_account_ids`, or validation rules to get a plan through.

#!/usr/bin/env bash
# Plan and apply one Terraform composition (one state) through a saved, reviewed plan.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: tf.sh <composition-dir> plan
       tf.sh <composition-dir> apply --yes
       tf.sh <composition-dir> discard

  plan      init, fmt check, validate, tflint, then save a plan and print a summary.
            Nothing in the cloud is changed.
  apply     apply exactly the saved plan (must be younger than 60 minutes). Needs --yes.
  discard   delete the saved plan.
EOF
}

die() { echo "error: $*" >&2; exit 1; }
log() { echo "==> $*" >&2; }

[ $# -ge 2 ] || { usage >&2; exit 1; }
[ -d "$1" ] || die "composition dir not found: $1"
DIR=$(cd "$1" && pwd)
CMD=$2
shift 2
YES=0
for arg in "$@"; do
  case $arg in
    --yes) YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

PLAN_MAX_AGE_MIN=60
PLAN_FILE=".terraform/claude.tfplan"
PLAN_TEXT=".terraform/claude.tfplan.txt"

command -v terraform >/dev/null || die "terraform not found"
cd "$DIR"
ls ./*.tf >/dev/null 2>&1 || die "no .tf files in $DIR"

json_summary() {
  if command -v jq >/dev/null; then
    jq -r '
      [.resource_changes[]? | .change.actions
        | if . == ["no-op"] or . == ["read"] then empty
          elif length == 2 then "replace" else .[0] end]
      | group_by(.) | map("  \(.[0]): \(length)") | .[]'
    return
  fi
  python3 -c '
import json, sys, collections
c = collections.Counter()
for r in json.load(sys.stdin).get("resource_changes", []):
    a = r["change"]["actions"]
    if a in (["no-op"], ["read"]): continue
    c["replace" if len(a) == 2 else a[0]] += 1
for k, v in sorted(c.items()): print(f"  {k}: {v}")'
}

json_destructive() {
  if command -v jq >/dev/null; then
    jq -r '.resource_changes[]? | select(.change.actions | index("delete"))
      | "  \(if (.change.actions | length) == 2 then "REPLACE" else "DESTROY" end)  \(.address)"'
    return
  fi
  python3 -c '
import json, sys
for r in json.load(sys.stdin).get("resource_changes", []):
    a = r["change"]["actions"]
    if "delete" in a: print(("  REPLACE  " if len(a) == 2 else "  DESTROY  ") + r["address"])'
}

aws_identity() {
  command -v aws >/dev/null || { echo "unknown (aws CLI not installed)"; return; }
  aws sts get-caller-identity --query '[Account, Arn]' --output text 2>/dev/null | tr '\t' ' ' \
    || echo "unavailable (no credentials for profile ${AWS_PROFILE:-default})"
}

find_tflint_config() {
  local d=$DIR
  while [ "$d" != "/" ]; do
    [ -f "$d/.tflint.hcl" ] && { echo "$d/.tflint.hcl"; return; }
    [ -d "$d/.git" ] && return
    d=$(dirname "$d")
  done
}

plan() {
  grep -Eq '^[[:space:]]*backend[[:space:]]+"' ./*.tf \
    || die "no backend block: compositions must use remote state"
  grep -Eq '^[[:space:]]*backend[[:space:]]+"local"' ./*.tf \
    && die "local backend is not allowed: compositions must use remote state"
  [ -f terraform.tfstate ] && die "local terraform.tfstate found in $DIR; move it to the remote backend first"

  log "terraform init"
  local lock_flag=""
  [ -f .terraform.lock.hcl ] && lock_flag="-lockfile=readonly"
  terraform init -input=false -no-color $lock_flag >/dev/null

  log "terraform fmt -check"
  terraform fmt -check -recursive -no-color || die "formatting issues; run terraform fmt"

  log "terraform validate"
  terraform validate -no-color >/dev/null || { terraform validate -no-color; exit 1; }

  local cfg
  cfg=$(find_tflint_config)
  if command -v tflint >/dev/null && [ -n "$cfg" ]; then
    log "tflint ($cfg)"
    tflint --init --config="$cfg" >/dev/null
    tflint --config="$cfg" --no-color
  else
    log "tflint skipped (not installed or no .tflint.hcl)"
  fi

  log "terraform plan"
  mkdir -p .terraform
  local rc=0
  terraform plan -input=false -no-color -lock-timeout=60s -detailed-exitcode -out="$PLAN_FILE" \
    > "$PLAN_TEXT" 2>&1 || rc=$?
  if [ "$rc" -eq 1 ]; then
    tail -n 60 "$PLAN_TEXT" >&2
    rm -f "$PLAN_FILE"
    die "terraform plan failed (full output: $DIR/$PLAN_TEXT)"
  fi

  local json
  json=$(terraform show -json "$PLAN_FILE")

  echo
  echo "Plan for $DIR"
  echo "  workspace  $(terraform workspace show)"
  echo "  identity   $(aws_identity)"
  echo
  if [ "$rc" -eq 0 ]; then
    rm -f "$PLAN_FILE"
    echo "No changes. Infrastructure matches the configuration."
    return
  fi
  echo "Changes:"
  printf '%s' "$json" | json_summary
  local destructive
  destructive=$(printf '%s' "$json" | json_destructive)
  if [ -n "$destructive" ]; then
    echo
    echo "DESTRUCTIVE CHANGES (resources destroyed or recreated):"
    echo "$destructive"
  fi
  echo
  echo "Full plan:  $DIR/$PLAN_TEXT"
  echo "Saved plan: $DIR/$PLAN_FILE (apply within $PLAN_MAX_AGE_MIN minutes with: apply --yes)"
}

apply() {
  [ "$YES" -eq 1 ] || die "apply needs --yes (only after the user approved the plan)"
  [ -f "$PLAN_FILE" ] || die "no saved plan; run plan first"
  [ -z "$(find "$PLAN_FILE" -mmin +$PLAN_MAX_AGE_MIN)" ] \
    || { rm -f "$PLAN_FILE"; die "saved plan is older than $PLAN_MAX_AGE_MIN minutes; run plan again"; }

  log "terraform apply (saved plan)"
  local rc=0
  terraform apply -input=false -no-color -lock-timeout=60s "$PLAN_FILE" || rc=$?
  # A saved plan cannot be applied twice, successful or not.
  rm -f "$PLAN_FILE"
  [ "$rc" -eq 0 ] || die "terraform apply failed"
}

case $CMD in
  plan) plan ;;
  apply) apply ;;
  discard) rm -f "$PLAN_FILE" "$PLAN_TEXT"; log "saved plan discarded" ;;
  *) usage >&2; exit 1 ;;
esac

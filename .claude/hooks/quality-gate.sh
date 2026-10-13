#!/usr/bin/env bash
# Claude Code quality gate for projects with any number of Python backends, JS/TS frontends,
# Flutter mobile apps, and Terraform modules/compositions.
#
#   post-edit  (PostToolUse on Edit|Write|MultiEdit)
#       Fast per-file checks on the edited file: ruff format + ruff check --fix, eslint --fix,
#       dart format, or terraform fmt. Remembers which root was touched.
#   stop       (Stop)
#       Project-wide checks for each touched root: mypy + lint-imports, typecheck + steiger,
#       flutter analyze + tool/check_layers.sh, or terraform validate + tflint.
#       (flutter test is left to CI: too slow for a stop hook.)
#       On failure, blocks the stop so Claude fixes the problems (max 3 attempts).
#
# A tool runs only if it is installed (.venv/bin, node_modules/.bin, .fvm/flutter_sdk/bin, or PATH for
# dart/flutter/terraform/tflint) and
# configured; otherwise it is skipped, so the hook is harmless in roots that have not been set up yet.
set -uo pipefail

MODE=${1:-}
PROJECT_DIR=${CLAUDE_PROJECT_DIR:-$(pwd)}
MAX_ATTEMPTS=3
OUTPUT_LINES=80

INPUT=$(cat)

json_get() {
  if command -v jq >/dev/null; then
    printf '%s' "$INPUT" | jq -r "$1 // empty"
  else
    printf '%s' "$INPUT" | python3 -c '
import json, sys
v = json.load(sys.stdin)
for k in sys.argv[1].lstrip(".").split("."):
    v = v.get(k) if isinstance(v, dict) else None
print("" if v is None else v)' "$1"
  fi
}

SESSION_ID=$(json_get .session_id)
STATE_DIR="${TMPDIR:-/tmp}/claude-quality-gate"
STATE_FILE="$STATE_DIR/${SESSION_ID:-default}.roots"
ATTEMPT_FILE="$STATE_DIR/${SESSION_ID:-default}.attempts"
mkdir -p "$STATE_DIR"

# Nearest ancestor of $1 (inclusive) containing file $2, not above the project dir.
find_root() {
  local dir=$1 marker=$2
  while :; do
    [ -f "$dir/$marker" ] && { echo "$dir"; return 0; }
    [ "$dir" = "$PROJECT_DIR" ] || [ "$dir" = "/" ] && return 1
    dir=$(dirname "$dir")
  done
}

py_tool() {
  if [ -x "$1/.venv/bin/$2" ]; then echo "$1/.venv/bin/$2"
  elif command -v "$2" >/dev/null; then command -v "$2"
  fi
}

# Looks upward too, for hoisted node_modules in workspaces.
js_tool() {
  local dir=$1
  while :; do
    [ -x "$dir/node_modules/.bin/$2" ] && { echo "$dir/node_modules/.bin/$2"; return; }
    [ "$dir" = "$PROJECT_DIR" ] || [ "$dir" = "/" ] && return
    dir=$(dirname "$dir")
  done
}

# Prefers the app's FVM-pinned SDK, then PATH.
dart_tool() {
  if [ -x "$1/.fvm/flutter_sdk/bin/$2" ]; then echo "$1/.fvm/flutter_sdk/bin/$2"
  elif command -v "$2" >/dev/null; then command -v "$2"
  fi
}

has_any() {
  local root=$1; shift
  for f in "$@"; do [ -e "$root/$f" ] && return 0; done
  return 1
}

remember_root() {
  grep -qxF "$1" "$STATE_FILE" 2>/dev/null || printf '%s\n' "$1" >> "$STATE_FILE"
}

post_edit() {
  local file root tool out
  file=$(json_get .tool_input.file_path)
  [ -n "$file" ] && [ -f "$file" ] || exit 0
  case $file in */node_modules/*|*/.venv/*|*/dist/*|*/build/*) exit 0 ;; esac

  case $file in
    *.py)
      root=$(find_root "$(dirname "$file")" pyproject.toml) || exit 0
      remember_root "py	$root"
      tool=$(py_tool "$root" ruff)
      [ -n "$tool" ] || exit 0
      (cd "$root" && "$tool" format --quiet "$file") >/dev/null 2>&1
      out=$(cd "$root" && "$tool" check --fix --quiet "$file" 2>&1) || {
        printf 'ruff found problems in %s:\n%s\n' "$file" "$(printf '%s' "$out" | tail -n $OUTPUT_LINES)" >&2
        exit 2
      }
      ;;
    *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs)
      root=$(find_root "$(dirname "$file")" package.json) || exit 0
      remember_root "js	$root"
      tool=$(js_tool "$root" eslint)
      [ -n "$tool" ] || exit 0
      has_any "$root" eslint.config.js eslint.config.mjs eslint.config.cjs eslint.config.ts \
        .eslintrc .eslintrc.js .eslintrc.cjs .eslintrc.json .eslintrc.yml || exit 0
      out=$(cd "$root" && "$tool" --fix "$file" 2>&1) || {
        printf 'eslint found problems in %s:\n%s\n' "$file" "$(printf '%s' "$out" | tail -n $OUTPUT_LINES)" >&2
        exit 2
      }
      ;;
    *.dart)
      case $file in *.g.dart|*.freezed.dart|*/.dart_tool/*|*/build/*) exit 0 ;; esac
      root=$(find_root "$(dirname "$file")" pubspec.yaml) || exit 0
      remember_root "dart	$root"
      tool=$(dart_tool "$root" dart)
      [ -n "$tool" ] || exit 0
      out=$(cd "$root" && "$tool" format "$file" 2>&1) || {
        printf 'dart format failed on %s (syntax error?):\n%s\n' "$file" "$(printf '%s' "$out" | tail -n $OUTPUT_LINES)" >&2
        exit 2
      }
      ;;
    *.tf|*.tfvars)
      case $file in */.terraform/*) exit 0 ;; esac
      remember_root "tf	$(dirname "$file")"
      command -v terraform >/dev/null || exit 0
      out=$(terraform fmt -no-color "$file" 2>&1) || {
        printf 'terraform fmt failed on %s (syntax error?):\n%s\n' "$file" "$(printf '%s' "$out" | tail -n $OUTPUT_LINES)" >&2
        exit 2
      }
      ;;
  esac
  exit 0
}

FAILURES=""

run_check() {
  local root=$1 label=$2; shift 2
  local out
  out=$(cd "$root" && "$@" 2>&1) || FAILURES+="
### $label failed in ${root#"$PROJECT_DIR"/}
$(printf '%s' "$out" | tail -n $OUTPUT_LINES)
"
}

check_python_root() {
  local root=$1 tool
  if grep -q '^\[tool\.mypy\]' "$root/pyproject.toml"; then
    tool=$(py_tool "$root" mypy)
    [ -n "$tool" ] && run_check "$root" mypy "$tool"
  fi
  if grep -q '^\[tool\.importlinter\]' "$root/pyproject.toml"; then
    tool=$(py_tool "$root" lint-imports)
    [ -n "$tool" ] && run_check "$root" "import-linter (hexagonal boundaries)" "$tool" --no-cache
  fi
}

check_js_root() {
  local root=$1 tool
  if grep -q '"typecheck"[[:space:]]*:' "$root/package.json"; then
    run_check "$root" typecheck npm run --silent typecheck
  elif [ -f "$root/tsconfig.json" ]; then
    tool=$(js_tool "$root" tsc)
    [ -n "$tool" ] && run_check "$root" tsc "$tool" --noEmit -p .
  fi
  if has_any "$root" steiger.config.ts steiger.config.js steiger.config.mjs steiger.config.json; then
    tool=$(js_tool "$root" steiger)
    [ -n "$tool" ] && [ -d "$root/src" ] && run_check "$root" "steiger (FSD boundaries)" "$tool" ./src
  fi
}

# Runs only once the app is set up (analysis_options.yaml), like [tool.mypy] for Python.
check_dart_root() {
  local root=$1 tool
  [ -f "$root/analysis_options.yaml" ] || return 0
  if grep -q 'sdk:[[:space:]]*flutter' "$root/pubspec.yaml"; then
    tool=$(dart_tool "$root" flutter)
    [ -n "$tool" ] && run_check "$root" "flutter analyze" "$tool" analyze
  else
    tool=$(dart_tool "$root" dart)
    [ -n "$tool" ] && run_check "$root" "dart analyze" "$tool" analyze
  fi
  if [ -x "$root/tool/check_layers.sh" ]; then
    run_check "$root" "layer boundaries (MVVM)" "$root/tool/check_layers.sh"
  fi
}

# Nearest .tflint.hcl at or above $1, not above the project dir.
find_tflint_config() {
  local dir=$1
  while :; do
    [ -f "$dir/.tflint.hcl" ] && { echo "$dir/.tflint.hcl"; return; }
    [ "$dir" = "$PROJECT_DIR" ] || [ "$dir" = "/" ] && return
    dir=$(dirname "$dir")
  done
}

check_terraform_dir() {
  local dir=$1 cfg
  ls "$dir"/*.tf >/dev/null 2>&1 || return 0
  # validate needs an initialized directory; never init here (it may touch the remote backend).
  if command -v terraform >/dev/null && [ -d "$dir/.terraform" ]; then
    run_check "$dir" "terraform validate" terraform validate -no-color
  fi
  cfg=$(find_tflint_config "$dir")
  if command -v tflint >/dev/null && [ -n "$cfg" ]; then
    tflint --init --config="$cfg" >/dev/null 2>&1
    run_check "$dir" tflint tflint --config="$cfg" --no-color
  fi
}

stop() {
  [ -s "$STATE_FILE" ] || exit 0

  local kind root
  while IFS=$'\t' read -r kind root; do
    [ -d "$root" ] || continue
    case $kind in
      py) check_python_root "$root" ;;
      js) check_js_root "$root" ;;
      dart) check_dart_root "$root" ;;
      tf) check_terraform_dir "$root" ;;
    esac
  done < "$STATE_FILE"

  if [ -z "$FAILURES" ]; then
    rm -f "$STATE_FILE" "$ATTEMPT_FILE"
    exit 0
  fi

  local attempts
  attempts=$(( $(cat "$ATTEMPT_FILE" 2>/dev/null || echo 0) + 1 ))
  if [ "$attempts" -gt "$MAX_ATTEMPTS" ]; then
    rm -f "$STATE_FILE" "$ATTEMPT_FILE"
    printf '{"systemMessage": "Quality gate still failing after %d attempts; stopping anyway. Run the checks manually."}\n' "$MAX_ATTEMPTS"
    exit 0
  fi
  echo "$attempts" > "$ATTEMPT_FILE"

  printf 'Quality gate failed (attempt %d/%d). Fix these before finishing; do not weaken the configs or add ignores to get around them:\n%s\n' \
    "$attempts" "$MAX_ATTEMPTS" "$FAILURES" >&2
  exit 2
}

case $MODE in
  post-edit) post_edit ;;
  stop) stop ;;
  *) echo "usage: quality-gate.sh post-edit|stop" >&2; exit 1 ;;
esac

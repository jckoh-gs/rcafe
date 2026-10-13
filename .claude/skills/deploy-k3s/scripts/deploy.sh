#!/usr/bin/env bash
# aicafe deploy helper. Pinned to kubectl context charles-k3s and namespace aicafe.
set -euo pipefail

CTX=charles-k3s
NS=aicafe
HOST=rcafe.koh.it.kr
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
KUBECTL=(kubectl --context "$CTX" -n "$NS")
# The plain-HTTP registry that already runs on the k3s server (other apps, e.g. chf, use it too).
IMAGE_PREFIX=${IMAGE_PREFIX:-121.143.126.21:5000}
PLATFORM=${PLATFORM:-linux/amd64}

die() { echo "error: $*" >&2; exit 1; }

guard() {
  [ "$(kubectl config current-context 2>/dev/null || true)" = "$CTX" ] || true  # context is always passed explicitly
  kubectl --context "$CTX" get ns "$NS" >/dev/null 2>&1 || die "namespace $NS not found in context $CTX"
}

image() { echo "${IMAGE_PREFIX:+$IMAGE_PREFIX/}$1:$2"; }

overlay() {  # overlay <tag> -> temp kustomization dir with the right image names
  local tag=$1 dir
  dir=$(mktemp -d)
  mkdir -p "$dir/base"
  cp -R "$ROOT/deploy/k8s/base/." "$dir/base/"
  cat > "$dir/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - base
images:
  - name: aicafe-backend
    newName: $(image aicafe-backend "$tag" | sed 's/:[^:/]*$//')
    newTag: "$tag"
  - name: aicafe-frontend
    newName: $(image aicafe-frontend "$tag" | sed 's/:[^:/]*$//')
    newTag: "$tag"
YAML
  echo "$dir"
}

cmd_check() {
  guard
  echo "context: $CTX  namespace: $NS"
  echo "node arch: $(kubectl --context "$CTX" get node -o jsonpath='{.items[0].status.nodeInfo.architecture}')"
  echo "traefik service: $(kubectl --context "$CTX" -n kube-system get svc traefik -o name 2>/dev/null || echo MISSING)"
  echo "dns $HOST: $(dig +short "$HOST" | head -1 || true)"
  "${KUBECTL[@]}" get pods,svc,ingress 2>/dev/null || true
}

cmd_secrets() {
  guard
  if ! "${KUBECTL[@]}" get secret aicafe-db >/dev/null 2>&1; then
    local pw; pw=$(openssl rand -hex 18)  # not tr|head: SIGPIPE kills the script under pipefail
    "${KUBECTL[@]}" create secret generic aicafe-db \
      --from-literal=POSTGRES_USER=aicafe --from-literal=POSTGRES_PASSWORD="$pw" --from-literal=POSTGRES_DB=aicafe
    : "${AICAFE_KMA_AUTH_KEY:?set AICAFE_KMA_AUTH_KEY to create the backend secret}"
    "${KUBECTL[@]}" create secret generic aicafe-backend \
      --from-literal=AICAFE_DATABASE_URL="postgresql+asyncpg://aicafe:${pw}@aicafe-db:5432/aicafe" \
      --from-literal=AICAFE_KMA_AUTH_KEY="$AICAFE_KMA_AUTH_KEY"
    echo "secrets created (values not shown)"
  else
    echo "secret aicafe-db already exists; leaving secrets untouched"
  fi
  admin_keys
}

# The admin page needs a login. Add the keys to the backend Secret once; existing values are never
# replaced, and nothing secret is printed (only the key names).
admin_keys() {
  "${KUBECTL[@]}" get secret aicafe-backend >/dev/null 2>&1 || return 0
  if "${KUBECTL[@]}" get secret aicafe-backend -o jsonpath='{.data.AICAFE_ADMIN_PASSWORD}' | grep -q .; then
    echo "admin keys already present in aicafe-backend"
    return 0
  fi
  local patch; patch=$(mktemp); chmod 600 "$patch"
  python3 - "$patch" <<'PY'
import json, secrets, sys
alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
password = "".join(secrets.choice(alphabet) for _ in range(24))
json.dump({"stringData": {
    "AICAFE_ADMIN_USER": "admin",
    "AICAFE_ADMIN_PASSWORD": password,
    "AICAFE_ADMIN_SESSION_KEY": secrets.token_hex(32),
}}, open(sys.argv[1], "w"))
PY
  "${KUBECTL[@]}" patch secret aicafe-backend --type merge --patch-file "$patch" >/dev/null
  rm -f "$patch"
  echo "added to aicafe-backend: AICAFE_ADMIN_USER, AICAFE_ADMIN_PASSWORD, AICAFE_ADMIN_SESSION_KEY (values not shown)"
}

cmd_build() {
  local tag=${1:?usage: build <tag>} name
  # A docker-container buildx builder can push to a plain-HTTP registry without touching the Docker
  # daemon settings (registry.insecure=true), and builds the node's architecture.
  docker buildx inspect aicafe-builder >/dev/null 2>&1 || docker buildx create --name aicafe-builder --driver docker-container >/dev/null
  for pair in "aicafe-backend:$ROOT/backend" "aicafe-frontend:$ROOT/frontend"; do
    name=${pair%%:*}
    docker buildx build --builder aicafe-builder --platform "$PLATFORM" \
      --output "type=image,name=$(image "$name" "$tag"),push=true,registry.insecure=true" "${pair#*:}"
  done
}

cmd_diff() {
  guard
  local dir; dir=$(overlay "${1:?usage: diff <tag>}")
  kubectl --context "$CTX" -n "$NS" diff -k "$dir" || true   # exit 1 just means "there are changes"
}

cmd_apply() {
  guard
  local tag=${1:?usage: apply <tag> --yes}; [ "${2:-}" = "--yes" ] || die "apply needs --yes after the diff was approved"
  local dir; dir=$(overlay "$tag")
  "${KUBECTL[@]}" apply -k "$dir"
  for d in aicafe-backend aicafe-frontend; do "${KUBECTL[@]}" rollout status "deployment/$d" --timeout=300s; done
  "${KUBECTL[@]}" rollout status statefulset/aicafe-db --timeout=300s
}

cmd_load_data() {
  guard
  local dump=${1:?usage: load-data <dump.sql.gz> [--replace]} replace=${2:-}
  [ -f "$dump" ] || die "no such file: $dump"
  local psql_cmd='psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
  if [ "$replace" = "--replace" ]; then
    # one transaction: the old data stays visible until the new data is fully loaded
    { echo "BEGIN;"; echo "TRUNCATE cafe, cafe_menu, cafe_review, cafe_taste, taste_archetype, taste_axis_stats CASCADE;"; gunzip -c "$dump"; echo "COMMIT;"; } \
      | "${KUBECTL[@]}" exec -i statefulset/aicafe-db -- sh -c "$psql_cmd" >/dev/null
    echo "data replaced"
  else
    gunzip -c "$dump" | "${KUBECTL[@]}" exec -i statefulset/aicafe-db -- sh -c "$psql_cmd" >/dev/null
    echo "data loaded"
  fi
}

cmd_job() {
  guard
  local name=${1:?usage: job <name> <cli-command>} cli=${2:?usage: job <name> <cli-command>} tag=${3:-latest}
  local dir; dir=$(overlay "$tag")
  local img; img=$(image aicafe-backend "$tag")
  sed -e "s/__NAME__/$name/" -e "s/__CMD__/$cli/" -e "s#image: aicafe-backend#image: $img#" \
    "$ROOT/deploy/k8s/jobs/job.yaml" | "${KUBECTL[@]}" create -f -
  rm -rf "$dir"
}

cmd_smoke() {
  guard
  "${KUBECTL[@]}" run smoke-$$ --rm -i --restart=Never --image=curlimages/curl:8.10.1 -- \
    -fsS "http://aicafe-backend:8000/healthz"
  echo
  if [ -n "$(dig +short "$HOST" | head -1)" ]; then
    curl -fsS -m 30 "http://$HOST/healthz" && echo " frontend ok via http://$HOST"
    curl -fsS -m 60 "http://$HOST/api/v1/recommendations?lat=37.5006&lng=127.0364" | head -c 200; echo
  else
    echo "DNS for $HOST is not set up yet; skipped the public check"
  fi
}

case "${1:-}" in
  check) shift; cmd_check "$@" ;;
  secrets) shift; cmd_secrets "$@" ;;
  build) shift; cmd_build "$@" ;;
  diff) shift; cmd_diff "$@" ;;
  apply) shift; cmd_apply "$@" ;;
  load-data) shift; cmd_load_data "$@" ;;
  job) shift; cmd_job "$@" ;;
  smoke) shift; cmd_smoke "$@" ;;
  *) echo "usage: deploy.sh check|secrets|build|diff|apply|load-data|job|smoke" >&2; exit 1 ;;
esac

#!/usr/bin/env bash
# Build a frontend and deploy it to a private S3 bucket served by CloudFront (OAC).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy.sh <frontend-dir> <env> [--yes] [--dry-run] [--wait]

Reads <frontend-dir>/.deploy/<env>.env, verifies the AWS setup, then (with --yes)
builds, uploads to S3 and invalidates CloudFront.

  (no flag)   Run checks and print the deploy plan only. Nothing is built or uploaded.
  --dry-run   Build and show what S3 sync would change. No upload, no invalidation.
  --yes       Actually deploy.
  --wait      After invalidating, wait until the invalidation completes.
EOF
}

die() { echo "error: $*" >&2; exit 1; }
log() { echo "==> $*" >&2; }

[ $# -ge 2 ] || { usage >&2; exit 1; }
[ -d "$1" ] || die "frontend dir not found: $1"
FRONTEND_DIR=$(cd "$1" && pwd)
ENV_NAME=$2
shift 2

YES=0 DRY_RUN=0 WAIT=0
for arg in "$@"; do
  case $arg in
    --yes) YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --wait) WAIT=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

CONFIG="$FRONTEND_DIR/.deploy/$ENV_NAME.env"
[ -f "$CONFIG" ] || die "config not found: $CONFIG"

# Export everything in the config so build-time vars (VITE_*, REACT_APP_*, ...) and
# AWS_PROFILE / AWS_REGION reach the build and the aws CLI.
set -a
# shellcheck disable=SC1090
. "$CONFIG"
set +a

[ -n "${S3_BUCKET:-}" ] || die "S3_BUCKET is not set in $CONFIG"
[ -n "${CLOUDFRONT_DISTRIBUTION_ID:-}" ] || die "CLOUDFRONT_DISTRIBUTION_ID is not set in $CONFIG"

# --- Preflight -------------------------------------------------------------

command -v aws >/dev/null || die "aws CLI not found"

ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) \
  || die "AWS credentials unavailable (profile: ${AWS_PROFILE:-default})"
if [ -n "${AWS_ACCOUNT_ID:-}" ] && [ "$ACCOUNT" != "$AWS_ACCOUNT_ID" ]; then
  die "current AWS account $ACCOUNT does not match AWS_ACCOUNT_ID=$AWS_ACCOUNT_ID"
fi

# The bucket must stay private: Block Public Access fully on (bucket or account level)
# and no public bucket policy.
all_true() { [ "$(echo "$1" | tr -s ' \t' ' ')" = "True True True True" ]; }
PAB_QUERY='PublicAccessBlockConfiguration.[BlockPublicAcls,IgnorePublicAcls,BlockPublicPolicy,RestrictPublicBuckets]'
pab=$(aws s3api get-public-access-block --bucket "$S3_BUCKET" --query "$PAB_QUERY" --output text 2>/dev/null || true)
if ! all_true "$pab"; then
  pab=$(aws s3control get-public-access-block --account-id "$ACCOUNT" --query "$PAB_QUERY" --output text 2>/dev/null || true)
  all_true "$pab" || die "S3 Block Public Access is not fully enabled for $S3_BUCKET (bucket or account level)"
fi
is_public=$(aws s3api get-bucket-policy-status --bucket "$S3_BUCKET" --query PolicyStatus.IsPublic --output text 2>/dev/null || echo "NoPolicy")
[ "$is_public" = "True" ] && die "bucket policy of $S3_BUCKET is public"

# CloudFront must reach the bucket through an Origin Access Control.
oac=$(aws cloudfront get-distribution --id "$CLOUDFRONT_DISTRIBUTION_ID" \
  --query "Distribution.DistributionConfig.Origins.Items[?starts_with(DomainName, '${S3_BUCKET}.s3.')].OriginAccessControlId | [0]" \
  --output json) || die "cannot read CloudFront distribution $CLOUDFRONT_DISTRIBUTION_ID"
case $oac in
  null) die "distribution $CLOUDFRONT_DISTRIBUTION_ID has no origin pointing at s3 bucket $S3_BUCKET" ;;
  '""') die "S3 origin of distribution $CLOUDFRONT_DISTRIBUTION_ID does not use Origin Access Control" ;;
esac
DOMAIN=$(aws cloudfront get-distribution --id "$CLOUDFRONT_DISTRIBUTION_ID" --query Distribution.DomainName --output text)

# --- Build settings --------------------------------------------------------

if [ -n "${BUILD_COMMAND:-}" ]; then
  build_cmd=$BUILD_COMMAND
elif [ -f "$FRONTEND_DIR/pnpm-lock.yaml" ]; then
  build_cmd="pnpm run build"
elif [ -f "$FRONTEND_DIR/yarn.lock" ]; then
  build_cmd="yarn build"
else
  build_cmd="npm run build"
fi

cat >&2 <<EOF

Deploy plan
  frontend      $FRONTEND_DIR
  environment   $ENV_NAME
  aws account   $ACCOUNT (profile: ${AWS_PROFILE:-default})
  s3 bucket     s3://$S3_BUCKET   (private, checked)
  cloudfront    $CLOUDFRONT_DISTRIBUTION_ID -> https://$DOMAIN   (OAC: ${oac//\"/})
  build         $build_cmd
  output dir    ${BUILD_DIR:-auto (dist or build)}

EOF

if [ "$YES" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
  log "Checks passed. Re-run with --dry-run to preview or --yes to deploy."
  exit 0
fi

# --- Build -----------------------------------------------------------------

cd "$FRONTEND_DIR"
[ -d node_modules ] || die "node_modules missing in $FRONTEND_DIR; install dependencies first"

log "Building: $build_cmd"
sh -c "$build_cmd"

if [ -n "${BUILD_DIR:-}" ]; then
  out=$BUILD_DIR
elif [ -d dist ]; then
  out=dist
elif [ -d build ]; then
  out=build
else
  die "build output not found; set BUILD_DIR in $CONFIG"
fi
[ -f "$out/index.html" ] || die "$out/index.html not found; is BUILD_DIR correct?"

# Content-hashed assets get long-lived caching; everything else must revalidate.
hashed=${HASHED_ASSETS_DIR:-}
if [ -z "$hashed" ]; then
  if [ -d "$out/assets" ]; then hashed=assets
  elif [ -d "$out/static" ]; then hashed=static
  fi
fi

dry=""
[ "$DRY_RUN" -eq 1 ] && dry="--dryrun"

# --- Upload ----------------------------------------------------------------

# Upload hashed assets first and never delete old ones, so clients still holding the
# previous index.html can load their chunks.
if [ -n "$hashed" ] && [ -d "$out/$hashed" ]; then
  log "Uploading $out/$hashed (immutable)"
  aws s3 sync "$out/$hashed" "s3://$S3_BUCKET/$hashed" \
    --cache-control "public,max-age=31536000,immutable" $dry
  log "Uploading remaining files (no-cache)"
  aws s3 sync "$out" "s3://$S3_BUCKET" --delete --exclude "$hashed/*" \
    --cache-control "no-cache" $dry
else
  log "Uploading $out (no-cache)"
  aws s3 sync "$out" "s3://$S3_BUCKET" --delete --cache-control "no-cache" $dry
fi

if [ "$DRY_RUN" -eq 1 ]; then
  log "Dry run complete. Nothing was uploaded or invalidated."
  exit 0
fi

# --- Invalidate ------------------------------------------------------------

inv=$(aws cloudfront create-invalidation --distribution-id "$CLOUDFRONT_DISTRIBUTION_ID" \
  --paths '/*' --query Invalidation.Id --output text)
log "Created invalidation $inv"
if [ "$WAIT" -eq 1 ]; then
  log "Waiting for invalidation to complete..."
  aws cloudfront wait invalidation-completed --distribution-id "$CLOUDFRONT_DISTRIBUTION_ID" --id "$inv"
fi

log "Deployed $ENV_NAME to https://$DOMAIN"

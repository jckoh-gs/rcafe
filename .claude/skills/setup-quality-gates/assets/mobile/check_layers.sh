#!/usr/bin/env bash
# Enforces the MVVM layer boundaries of .claude/rules/mobile-flutter-mvvm.md for one Flutter app.
# Copy to <app>/tool/check_layers.sh (chmod +x). Run from anywhere; it checks the app it lives in.
#
# Needs only grep/find. It reads `package:<name>/...` imports, so keep `always_use_package_imports`
# enabled in analysis_options.yaml (relative imports would bypass this check).
#
#   View       lib/**/view/**        must not import data / repositories / services
#   ViewModel  lib/**/view_model/**  must not import flutter UI, services, or view
#   Domain     lib/domain/**         must not import flutter, data, or features
#   Data       lib/data/**           must not import view, view_model, or features
#   Features   lib/features/<a>/**   must not import features/<b>/view or features/<b>/view_model
set -uo pipefail

APP_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$APP_DIR" || exit 1
[ -d lib ] && [ -f pubspec.yaml ] || { echo "check_layers: no lib/ or pubspec.yaml in $APP_DIR" >&2; exit 1; }

PKG=$(sed -n 's/^name:[[:space:]]*\([A-Za-z0-9_]*\).*/\1/p' pubspec.yaml | head -n1)
[ -n "$PKG" ] || { echo "check_layers: cannot read package name from pubspec.yaml" >&2; exit 1; }

IMPORT="^[[:space:]]*(import|export)[[:space:]]+['\"]"
OWN="package:$PKG/([^'\"]*/)?"
VIOLATIONS=0

# check <file> <message> <regex matched against the import line>
check() {
  local file=$1 msg=$2 re=$3 hits
  hits=$(grep -nE "${IMPORT}.*(${re})" "$file" || true)
  [ -n "$hits" ] || return 0
  while IFS= read -r line; do
    printf '%s:%s  %s\n' "$file" "${line%%:*}" "$msg"
    VIOLATIONS=$((VIOLATIONS + 1))
  done <<< "$hits"
}

while IFS= read -r f; do
  case $f in
    */view/*)
      check "$f" "View must not import data/repositories/services; go through its ViewModel" \
        "${OWN}(data|repositories|services)/" ;;
    */view_model/*)
      check "$f" "ViewModel must not import Flutter UI (BuildContext/widgets); expose state instead" \
        "package:flutter/(material|widgets|cupertino)\.dart"
      check "$f" "ViewModel must not import services directly; go through a Repository" \
        "${OWN}services/"
      check "$f" "ViewModel must not import view code" \
        "${OWN}view/" ;;
  esac

  case $f in
    lib/domain/*)
      check "$f" "domain must be pure Dart: no Flutter imports" "package:flutter/"
      check "$f" "domain must not depend on the data layer or features" \
        "${OWN}(data|features)/" ;;
    lib/data/*)
      check "$f" "data layer must not import UI layers or features" \
        "${OWN}(view|view_model|features)/" ;;
  esac

  case $f in
    lib/features/*/*)
      own_feature=${f#lib/features/}; own_feature=${own_feature%%/*}
      while IFS= read -r hit; do
        [ -n "$hit" ] || continue
        other=$(printf '%s' "$hit" | sed -E "s#.*package:$PKG/([^'\"]*/)?features/([^/'\"]+)/(view|view_model)/.*#\2#")
        [ "$other" = "$own_feature" ] && continue
        printf '%s:%s  feature "%s" must not import UI code of feature "%s"; share via domain/ or shared/\n' \
          "$f" "${hit%%:*}" "$own_feature" "$other"
        VIOLATIONS=$((VIOLATIONS + 1))
      done < <(grep -nE "${IMPORT}.*package:$PKG/([^'\"]*/)?features/[^/'\"]+/(view|view_model)/" "$f" || true)
      ;;
  esac
done < <(find lib -type f -name '*.dart' ! -name '*.g.dart' ! -name '*.freezed.dart' | sort)

if [ "$VIOLATIONS" -gt 0 ]; then
  printf '\n%d layer violation(s). See .claude/rules/mobile-flutter-mvvm.md.\n' "$VIOLATIONS" >&2
  exit 1
fi
echo "layer boundaries ok"

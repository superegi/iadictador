#!/usr/bin/env bash
set -Ee

cd "$(dirname "$0")/.." || exit 1

TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="exports"
mkdir -p "$OUT_DIR"

OUT="$OUT_DIR/iadictador_intelligence_pack_${TS}.tar.gz"

tar -czf "$OUT" \
  app/services/ai/intelligence_pack \
  app/services/ai/prompts \
  app/services/ai/schemas \
  report_templates

echo "$OUT"

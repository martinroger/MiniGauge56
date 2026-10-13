#!/usr/bin/env bash
# Host-side checks for the LCD emulator decorator.
#   ./run_host_checks.sh [fuzz-iterations] [seed]
# Builds the unit tests, the differential fuzz and the benchmark at LV_COLOR_DEPTH 8 and 16, with
# -Wall -Wextra, and runs them. The baseline implementation is taken from git history (BASE_REF),
# its public symbols renamed with a ref_ prefix; ASAN=1 adds AddressSanitizer + UBSan.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(git rev-parse --show-toplevel)"
BASE_REF="${BASE_REF:-2762974}"
ITERS="${1:-200000}"
SEED="${2:-1}"
OUT="${OUT_DIR:-$(mktemp -d)}"
SAN=""
if [ "${ASAN:-0}" = "1" ]; then SAN="-fsanitize=address,undefined -fno-omit-frame-pointer"; fi
OPT="${OPT:--O2}"

git -C "$ROOT" show "$BASE_REF:components/lcd_emulator/src/lcd_emulator.c" > "$OUT/ref_lcd_emulator.c"
RENAMES=$(grep -o 'lcd_emulator_[a-z0-9_]*(' ../include/lcd_emulator.h | tr -d '(' | sort -u | sed 's/.*/-D&=ref_&/' | tr '\n' ' ')

for DEPTH in 8 16; do
  echo "=== LV_COLOR_DEPTH=$DEPTH ==="
  gcc $OPT $SAN -Wall -Wextra -DLV_COLOR_DEPTH=$DEPTH -I../include -c ../src/lcd_emulator.c -o "$OUT/new$DEPTH.o"
  # shellcheck disable=SC2086
  gcc $OPT $SAN -w -DLV_COLOR_DEPTH=$DEPTH -I../include $RENAMES -c "$OUT/ref_lcd_emulator.c" -o "$OUT/ref$DEPTH.o"
  g++ $OPT $SAN -std=c++17 -Wall -Wextra -DLV_COLOR_DEPTH=$DEPTH -I../include lcd_diff_bench.cpp \
      "$OUT/new$DEPTH.o" "$OUT/ref$DEPTH.o" -o "$OUT/diff$DEPTH"
  g++ $OPT $SAN -std=c++17 -Wall -DLV_COLOR_DEPTH=$DEPTH -I../include test_lcd_emulator.cpp -o "$OUT/unit$DEPTH"
  "$OUT/unit$DEPTH" | tail -3
  "$OUT/diff$DEPTH" fuzz "$ITERS" "$SEED"
  if [ "${BENCH:-0}" = "1" ] && [ "$DEPTH" = "8" ]; then "$OUT/diff$DEPTH" bench; fi
done
echo "host checks OK (artifacts in $OUT)"

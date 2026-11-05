#!/bin/bash
# namo/bootstrap.sh — bring every runtime to a working state, once.
# Safe to re-run. Every step reports rather than aborts, except a missing node.
set -u
cd "$(dirname "$0")/.."
OK=0; FAIL=0
step(){ local n="$1"; shift; if "$@" >/tmp/b.log 2>&1; then echo "ok   $n"; OK=$((OK+1)); else echo "FAIL $n"; tail -3 /tmp/b.log|sed 's/^/       /'; FAIL=$((FAIL+1)); fi; }

command -v node >/dev/null || { echo "node is required"; exit 1; }
command -v ffmpeg >/dev/null || echo "warn ffmpeg missing (compose will fail)"

# 1. ft-motion — the baap of the vector renderers; it vendors lemo AND carries the
#    animation/ emotion kit (31 acted emotions, mocap, p5.brush). One clone, two engines.
if [ ! -d ftm ]; then
  step "clone ft-motion" git clone --depth 1 https://github.com/imserhatdemir/ft-motion.git ftm
fi
if [ -d ftm ]; then
  ( cd ftm && [ -d node_modules ] || npm install --no-audit --no-fund >/tmp/npm.log 2>&1 ) && echo "ok   ft-motion deps" || { echo "FAIL ft-motion deps"; FAIL=$((FAIL+1)); }
fi

# 2. lemo directly, for pipelines that want the 68 styles without ft-motion's wrapper
if [ ! -d lemo ]; then
  step "clone lemo-opuscar" git clone --depth 1 https://github.com/lemomo-ai/lemo-opuscar.git lemo
fi
if [ -d lemo ] && [ ! -d lemo/node_modules ]; then
  ( cd lemo && npm install --no-audit --no-fund >/tmp/npm2.log 2>&1 ) && echo "ok   lemo deps" || { echo "FAIL lemo deps"; FAIL=$((FAIL+1)); }
fi

# 3. fonts — the style ships licence files only. Fetch the real faces (every one guarded).
for base in lemo ftm/lemo; do
  F="$base/styles/ink-wash/demo/fonts"
  [ -d "$base" ] || continue
  mkdir -p "$F"
  for u in cormorantsc/CormorantSC-Regular.ttf cormorantsc/CormorantSC-SemiBold.ttf \
           cormorantgaramond/CormorantGaramond%5Bwght%5D.ttf cormorantgaramond/CormorantGaramond-Italic%5Bwght%5D.ttf \
           mashanzheng/MaShanZheng-Regular.ttf zhimangxing/ZhiMangXing-Regular.ttf \
           notoserifdevanagari/NotoSerifDevanagari%5Bwdth,wght%5D.ttf; do
    n=$(basename "$u" | sed 's/%5B.*%5D/-VF/')
    [ -s "$F/$n" ] || curl -fsSL -o "$F/$n" "https://github.com/google/fonts/raw/main/ofl/$u" || true
  done
  echo "ok   fonts in $F ($(ls "$F" 2>/dev/null | wc -l) files)"
done

# 4. python side (audio, mix, checking)
python3 -m venv .venv >/dev/null 2>&1 || true
if [ -x .venv/bin/pip ]; then
  .venv/bin/pip install -q --upgrade pip >/dev/null 2>&1
  .venv/bin/pip install -q numpy scipy pillow requests pyyaml >/tmp/pip.log 2>&1 \
    && echo "ok   python deps" || { echo "FAIL python deps"; tail -3 /tmp/pip.log; FAIL=$((FAIL+1)); }
fi

echo "---"
echo "bootstrap: $OK ok, $FAIL failed"
python3 namo/engine.py probe || true
exit 0

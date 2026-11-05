set -x
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg chromium-browser 2>/dev/null || sudo apt-get install -y -qq chromium
command -v chromium chromium-browser google-chrome 2>/dev/null
corepack enable 2>/dev/null || npm i -g pnpm@9
git clone --depth 1 https://github.com/thecodacus/rendiv.git rd
cd rd
cat package.json
echo "=== install ==="
pnpm install --frozen-lockfile 2>&1 | tail -20 || pnpm install 2>&1 | tail -20
echo "=== example ==="
ls examples/hello-world
cat examples/hello-world/*.tsx 2>/dev/null | head -60
echo "=== build packages ==="
pnpm build 2>&1 | tail -25
echo "=== cli ==="
node packages/cli/dist/index.js --help 2>&1 | head -20 || npx rendiv --help 2>&1 | head -20

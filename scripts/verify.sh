#!/usr/bin/env bash
# Release gate. Runs from the repository root; never contacts Home Assistant.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q

for translation in custom_components/cinema_studio/translations/*.json; do
    [ -e "$translation" ] || continue
    uv run python -m json.tool "$translation" >/dev/null
done

if [ -f app/ui/package.json ] && command -v npm >/dev/null 2>&1; then
    npm --prefix app/ui ci
    npm --prefix app/ui run test:unit
    npm --prefix app/ui run build
else
    echo "Skipped UI tests/build (no npm or no UI yet)." >&2
fi

if [ -f app/Dockerfile ] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    case "$(uname -m)" in
        arm64 | aarch64) build_arch=aarch64 ;;
        *) build_arch=amd64 ;;
    esac
    docker build --build-arg "BUILD_ARCH=${build_arch}" --file app/Dockerfile --tag cinema-studio:verify app
else
    echo "Skipped Docker build (daemon unavailable); CI builds the image." >&2
fi

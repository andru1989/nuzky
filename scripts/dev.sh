#!/usr/bin/env bash
# Runs the desktop app from this checkout (`npm run tauri dev`). The interface reloads as you save; Rust changes
# rebuild the app.
#
#   scripts/dev.sh               data, cache and socket of its own in tmp-test/dev: never opens or autosaves your
#                                own projects and never attaches to the Nuzky you have open
#   scripts/dev.sh --fresh       the same, starting with empty data
#   scripts/dev.sh --real-data   your own Nuzky folders: projects, models, styles, chats and caches. A build in
#                                progress can damage a project, so the projects, caption styles and editing style
#                                are copied to a dated backup first, and it refuses to start while an installed
#                                Nuzky runs, which would edit the same files.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
real=false
case "${1:-}" in
  --real-data) real=true; shift ;;
  --fresh) rm -rf "$root/tmp-test/dev"; shift ;;
esac

env=(NUZKY_NO_UPDATE_CHECK=1)
if [ "$(uname -s)" = Darwin ]; then
  # The exports of docs/BUILDING.md.
  env+=(PKG_CONFIG_PATH="$(brew --prefix ffmpeg@8)/lib/pkgconfig" SDKROOT="$(xcrun --sdk macosx --show-sdk-path)")
fi

if $real; then
  if pgrep -f '/Nuzky.app/Contents/MacOS/nuzky-app$' >/dev/null || pgrep -fx 'nuzky-app' >/dev/null; then
    echo "Quit the installed Nuzky first: both would edit the same projects." >&2
    exit 1
  fi
  if [ "$(uname -s)" = Darwin ]; then
    data="$HOME/Library/Application Support/nuzky"
  else
    data="${NUZKY_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/nuzky}"
  fi
  if [ -d "$data" ]; then
    backup="$data-backups/$(date +%Y-%m-%d_%H-%M-%S)"
    mkdir -p "$backup"
    for item in projects caption-styles.json style; do
      [ -e "$data/$item" ] && cp -Rp "$data/$item" "$backup/"
    done
    echo "Backed up your projects and styles to $backup"
  fi
else
  dev=$root/tmp-test/dev
  data=$dev/data cache=$dev/cache
  runtime=$(mktemp -d "${TMPDIR:-/tmp}/nuzky-dev.XXXXXX")
  trap 'rm -rf "$runtime"' EXIT
  mkdir -p "$data/nuzky" "$cache/nuzky"
  env+=(XDG_DATA_HOME="$data" XDG_CACHE_HOME="$cache" XDG_RUNTIME_DIR="$runtime")
  if [ "$(uname -s)" = Darwin ]; then
    # macOS ignores the XDG variables and keeps Nuzky's data, cache and webview storage under ~/Library, so the
    # app gets a home of its own whose Library folders lead to the folders above. Cargo, rustup and the build
    # dependencies stay in the real home.
    home=$dev/home
    mkdir -p "$home/Library/Application Support" "$home/Library/Caches"
    ln -sfn "$data/nuzky" "$home/Library/Application Support/nuzky"
    ln -sfn "$cache/nuzky" "$home/Library/Caches/nuzky"
    env+=(
      HOME="$home"
      CARGO_HOME="${CARGO_HOME:-$HOME/.cargo}"
      RUSTUP_HOME="${RUSTUP_HOME:-$HOME/.rustup}"
      NUZKY_DEPS="${NUZKY_DEPS:-$HOME/.cache/nuzky/deps}"
      npm_config_cache="${npm_config_cache:-$HOME/.npm}"
    )
  fi
  env=(-u NUZKY_DATA_DIR "${env[@]}")
fi
cd "$root"
env "${env[@]}" npm run tauri dev -- "$@"

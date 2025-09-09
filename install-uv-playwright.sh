#!/usr/bin/env bash
set -euo pipefail

UV_BIN="${HOME}/.local/bin/uv"

log() { printf "\033[1;32m[info]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[err ]\033[0m %s\n" "$*" >&2; }

ensure_path_contains_local_bin() {
  # Make sure ~/.local/bin is on PATH for this session
  if ! printf "%s" "$PATH" | tr ":" "\n" | grep -qx "$HOME/.local/bin"; then
    export PATH="$HOME/.local/bin:$PATH"
    log "Temporarily added \$HOME/.local/bin to PATH for this session."
  fi

  # Try to persist it for future shells if not already present
  local rcfile
  for rcfile in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
    if [[ -f "$rcfile" ]] && ! grep -qs 'export PATH="$HOME/.local/bin:$PATH"' "$rcfile"; then
      printf '\n# Ensure local user bin is on PATH for uv/playwright\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rcfile"
      log "Added \$HOME/.local/bin to PATH in $rcfile"
      break
    fi
  done
}

install_uv_if_needed() {
  if command -v uv >/dev/null 2>&1; then
    log "uv already installed: $(command -v uv)"
    return
  fi

  # Try known default location if not on PATH yet
  if [[ -x "$UV_BIN" ]]; then
    log "uv found at $UV_BIN"
    return
  fi

  log "Installing uv..."
  # Install script (non-interactive); idempotent
  wget -qO- https://astral.sh/uv/install.sh | sh
  ensure_path_contains_local_bin

  if ! command -v uv >/dev/null 2>&1; then
    # Last resort: check direct path
    if [[ -x "$UV_BIN" ]]; then
      log "uv installed at $UV_BIN"
    else
      err "uv installation did not complete or is not on PATH."
      exit 1
    fi
  fi

  log "uv version: $(uv --version)"
}

install_py_deps() {
  # Use uv's pip wrapper for speed; -U makes it idempotent (upgrade if needed)
  log "Installing/upgrading pytest-playwright..."
  uv pip install -U pytest-playwright

  # Optionally ensure 'playwright' package is present explicitly (often pulled in by pytest-playwright)
  if ! python -c "import playwright" >/dev/null 2>&1; then
    log "Installing Playwright Python package..."
    uv pip install -U playwright
  fi
}

install_browsers() {
  # Install browser binaries (idempotent; it will skip what’s already installed)
  if command -v playwright >/dev/null 2>&1; then
    log "Running 'playwright install' (idempotent)…"
    playwright install
  else
    # Fallback via module if bin isn't exposed (rare)
    log "Running 'python -m playwright install' (idempotent)…"
    python -m playwright install
  fi
}

mv_env() {
  local src_file=".env"
  local dest_file=".env_default"

  if [[ -f "$src_file" ]]; then
    if [[ -f "$dest_file" ]]; then
      warn "$dest_file already exists. Not overwriting."
    else
      mv "$src_file" "$dest_file"
      log "Renamed $src_file to $dest_file"
    fi
  else
    warn "$src_file does not exist. Nothing to rename."
  fi
}

main() {
  mv_env
  ensure_path_contains_local_bin
  install_uv_if_needed
  install_py_deps
  install_browsers

  log "Done!"
}

main "$@"

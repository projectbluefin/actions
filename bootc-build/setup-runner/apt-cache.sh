#!/usr/bin/env bash
# Shared cache mechanics for native Ubuntu packages and the resolute Podman stack.
set -euo pipefail

read -r -a packages <<< "${APT_PACKAGES:-}"
for package in "${packages[@]}"; do
  # Package names only: no apt options, release selectors, or shell syntax.
  if [[ ! "$package" =~ ^[a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?$ ]]; then
    echo "::error::apt-packages must contain space-separated Ubuntu package names: '$package'"
    exit 1
  fi
done
package_hash=$(printf '%s\n' "${packages[@]}" | LC_ALL=C sort -u | sha256sum | cut -d' ' -f1)

case "${1:?expected key or install}" in
  key)
    # Dependencies vary with the hosted runner image's preinstalled packages.
    # Do not restore across image versions (or native package lists for Podman).
    image="${ImageOS:-${RUNNER_OS}}-${RUNNER_ARCH}-${ImageVersion:-unknown}"
    week=$(date +%Y-W%V)
    if [[ "$APT_MODE" == resolute ]]; then
      key="apt-resolute-podman-${RUNNER_OS}-${image}-${package_hash}-${week}"
    else
      key="apt-pkgs-${image}-${package_hash}-${week}"
    fi
    echo "key=$key" >> "$GITHUB_OUTPUT"
    ;;
  install)
    if [[ "$APT_MODE" == resolute ]]; then
      packages=(crun/resolute buildah/resolute podman/resolute skopeo/resolute)
      install_opts=(--allow-downgrades)
      # Keep rsyslog running with its old mapped library during noble→resolute
      # upgrades. Restarting it can kill runner log connectivity mid-build.
      sudo mkdir -p /etc/needrestart/conf.d
      # shellcheck disable=SC2016 # Literal Perl configuration, not shell expansion.
      echo '$nrconf{restart} = "l";' | sudo tee /etc/needrestart/conf.d/99-no-restarts.conf
      trap 'sudo rm -f /etc/needrestart/conf.d/99-no-restarts.conf' EXIT
    else
      install_opts=(--no-install-recommends)
    fi
    # Keep the existing mirror retries/timeouts: Azure can drop connections
    # mid-download, and a stalled mirror must not consume the whole job.
    # apt (unlike apt-get) normally deletes downloaded packages after install.
    APT_OPTS=(-o Acquire::Retries=5 -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60
      -o Binary::apt::APT::Keep-Downloaded-Packages=true)

    restore_cache() {
      sudo mkdir -p /var/cache/apt/archives /var/lib/apt/lists || return
      sudo find "$APT_CACHE_DIR/archives" -maxdepth 1 -type f -name '*.deb' \
        -exec cp -t /var/cache/apt/archives/ -- {} + || return
      sudo find "$APT_CACHE_DIR/lists" -maxdepth 1 -type f ! -name lock \
        -exec cp -t /var/lib/apt/lists/ -- {} + || return
    }
    cached_install=false
    if [[ "${APT_CACHE_HIT:-false}" == true ]]; then
      # No update and no network downloads on a usable hit. An incomplete or
      # stale cache must never prevent the normal mirror-backed fallback.
      if restore_cache && sudo apt "${APT_OPTS[@]}" install -y --no-download "${install_opts[@]}" "${packages[@]}"; then
        cached_install=true
      else
        echo '::warning::Cached apt install failed; refreshing from Ubuntu mirrors.'
      fi
    fi
    if [[ "$cached_install" != true ]]; then
      time sudo apt "${APT_OPTS[@]}" update
      time sudo apt "${APT_OPTS[@]}" install -y "${install_opts[@]}" "${packages[@]}"
    fi

    if [[ "${APT_CACHE_HIT:-false}" != true ]]; then
      # These system folders are root-owned. Caching them directly failed to
      # save, leaving every build exposed to the 2026-11-11 mirror outage.
      # Stage only regular package/list files, never lock/partial/auxfiles.
      mkdir -p "$APT_CACHE_DIR/archives" "$APT_CACHE_DIR/lists"
      sudo find /var/cache/apt/archives -maxdepth 1 -type f -name '*.deb' \
        -exec cp -t "$APT_CACHE_DIR/archives/" -- {} +
      sudo find /var/lib/apt/lists -maxdepth 1 -type f ! -name lock \
        -exec cp -t "$APT_CACHE_DIR/lists/" -- {} +
      sudo chown -R "$(id -u):$(id -g)" "$APT_CACHE_DIR"
    fi
    if [[ "$APT_MODE" == resolute ]]; then
      podman --version
      buildah --version
      crun --version
      skopeo --version
    fi
    ;;
  *) echo '::error::expected key or install'; exit 1 ;;
esac

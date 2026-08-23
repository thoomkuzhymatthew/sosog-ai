#!/usr/bin/env bash
set -Eeuo pipefail

readonly expected_version='0.149.0'
readonly source_link='/home/ubuntu/.codex/packages/standalone/current'
readonly runtime_root='/opt/sosog/codex-cli'
readonly target_root="${runtime_root}/${expected_version}"
readonly current_link="${runtime_root}/current"
readonly profile_name='sosog-codex-bwrap'

if [[ ${EUID} -ne 0 ]]; then
  printf 'run this installer as root\n' >&2
  exit 2
fi

for command_name in apparmor_parser chmod chown cmp cp find install jq ln realpath systemd-run; do
  command -v "$command_name" >/dev/null || {
    printf 'required command is unavailable: %s\n' "$command_name" >&2
    exit 69
  }
done

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
profile_source="${script_dir}/apparmor-sosog-codex-bwrap"
if [[ ! -f $profile_source ]]; then
  printf 'AppArmor profile is missing: %s\n' "$profile_source" >&2
  exit 66
fi

source_root=$(realpath -e -- "$source_link")
package_version=$(jq -r '.version' "${source_root}/codex-package.json")
if [[ $package_version != "$expected_version" ]]; then
  printf 'expected Codex %s, found %s\n' "$expected_version" "$package_version" >&2
  exit 65
fi

for source_file in \
  "${source_root}/bin/codex" \
  "${source_root}/bin/codex-code-mode-host" \
  "${source_root}/codex-resources/bwrap" \
  "${source_root}/codex-path/rg"; do
  if [[ ! -x $source_file ]]; then
    printf 'standalone support executable is unavailable: %s\n' "$source_file" >&2
    exit 69
  fi
done

install -d -m 0755 -o root -g root "$runtime_root"
if [[ ! -e $target_root ]]; then
  cp -a -- "$source_root" "$target_root"
fi
if [[ ! -d $target_root || -L $target_root ]]; then
  printf 'runtime target must be a real directory: %s\n' "$target_root" >&2
  exit 73
fi

for relative_file in \
  bin/codex \
  bin/codex-code-mode-host \
  codex-resources/bwrap \
  codex-path/rg \
  codex-package.json; do
  if ! cmp -s -- "${source_root}/${relative_file}" "${target_root}/${relative_file}"; then
    printf 'installed runtime differs from authenticated source: %s\n' \
      "$relative_file" >&2
    exit 65
  fi
done
chown -R root:root "$target_root"
find "$target_root" -type d -exec chmod go-w {} +
chmod 0755 \
  "${target_root}/bin/codex" \
  "${target_root}/bin/codex-code-mode-host" \
  "${target_root}/codex-resources/bwrap" \
  "${target_root}/codex-path/rg"

if [[ -e $current_link || -L $current_link ]]; then
  if [[ $(realpath -e -- "$current_link") != "$target_root" ]]; then
    printf 'current runtime link points somewhere unexpected: %s\n' "$current_link" >&2
    exit 73
  fi
else
  ln -s -- "$target_root" "$current_link"
fi

install -m 0644 -o root -g root "$profile_source" \
  "/etc/apparmor.d/${profile_name}"
apparmor_parser -r "/etc/apparmor.d/${profile_name}"

# This uses a fresh systemd service context, matching the condition that
# previously failed under Ubuntu's unprivileged-user-namespace restriction.
systemd-run --quiet --wait --pipe --collect --uid=ubuntu \
  "${target_root}/bin/codex" sandbox -- /bin/true

printf 'installed root-owned Codex runtime %s at %s\n' \
  "$expected_version" "$target_root"

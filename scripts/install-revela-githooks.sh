#!/bin/sh
set -eu
repo_root=$(git rev-parse --show-toplevel)
chmod +x "$repo_root/githooks/pre-commit"
git -C "$repo_root" config core.hooksPath githooks
printf '%s\n' "RevelaCode non-destructive secret-check hook enabled for this checkout."
printf '%s\n' "This hook blocks key material; it does not encrypt/delete existing Go or Python source."

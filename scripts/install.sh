#!/usr/bin/env bash
set -euo pipefail
exec python "$(dirname "${BASH_SOURCE[0]}")/install.py" "$@"

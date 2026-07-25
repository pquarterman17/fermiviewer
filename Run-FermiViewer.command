#!/bin/sh

cd -- "$(dirname -- "$0")" || exit 1

if ! command -v uv >/dev/null 2>&1; then
    echo "FermiViewer could not start because uv is not installed or is not on PATH."
    echo "Install uv from https://docs.astral.sh/uv/ and try again."
    printf "Press Return to close..."
    read -r _
    exit 1
fi

exec uv run fv "$@"

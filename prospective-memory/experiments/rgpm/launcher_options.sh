#!/usr/bin/env bash

rgpm_bool() {
  case "${1:-0}" in
    1|true|TRUE|yes|YES) printf '1\n' ;;
    0|false|FALSE|no|NO|'') printf '0\n' ;;
    *) printf 'Invalid boolean flag value: %s\n' "$1" >&2; return 2 ;;
  esac
}

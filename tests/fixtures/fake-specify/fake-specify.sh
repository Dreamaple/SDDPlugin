#!/usr/bin/env bash
# T008: fake-specify POSIX 包装器
exec node "$(dirname "$0")/fake-specify.js" "$@"
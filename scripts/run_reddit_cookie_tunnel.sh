#!/bin/zsh
# Launchd entrypoint for the encrypted Unix-socket forward to EC2.

set -eu

ssh_host="${REDDIT_SOLVER_SSH_HOST:-panicradar}"
remote_socket="${REDDIT_SOLVER_REMOTE_SOCKET:-/opt/crypto-sentiment/run/reddit-cookie-solver.sock}"
local_host="${REDDIT_SOLVER_LOCAL_HOST:-127.0.0.1}"
local_port="${REDDIT_SOLVER_LOCAL_PORT:-18765}"

exec /usr/bin/ssh \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o StreamLocalBindUnlink=yes \
  -o StreamLocalBindMask=0177 \
  -R "${remote_socket}:${local_host}:${local_port}" \
  -N "$ssh_host"

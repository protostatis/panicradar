#!/bin/zsh
# Launchd entrypoint for the encrypted Unix-socket forward to EC2.

set -eu

ssh_host="${REDDIT_SOLVER_SSH_HOST:-panicradar}"
remote_dir="${REDDIT_SOLVER_REMOTE_DIR:-/opt/crypto-sentiment/run/reddit-solver}"
remote_socket="${REDDIT_SOLVER_REMOTE_SOCKET:-${remote_dir}/reddit-cookie-solver.sock}"
local_host="${REDDIT_SOLVER_LOCAL_HOST:-127.0.0.1}"
local_port="${REDDIT_SOLVER_LOCAL_PORT:-18765}"

# The crawler bind-mounts the parent directory, not the socket file, so the
# socket may be recreated without staling the container mount. Ensure that
# directory exists, and clear only this fixed stale listener: sshd can leave a
# Unix listener behind after an unclean tunnel exit, which would otherwise
# block the supervised retry.
/usr/bin/ssh \
  -o BatchMode=yes \
  -o ConnectTimeout=15 \
  "$ssh_host" \
  "mkdir -p -- '${remote_dir}' && rm -f -- '${remote_socket}'"

exec /usr/bin/ssh \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o StreamLocalBindUnlink=yes \
  -o StreamLocalBindMask=0177 \
  -R "${remote_socket}:${local_host}:${local_port}" \
  -N "$ssh_host"

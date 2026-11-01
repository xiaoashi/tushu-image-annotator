#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ -d dist/图枢网页.app ]]; then
 exec /usr/bin/open -a "$PWD/dist/图枢网页.app"
fi
if [[ ! -x .venv/bin/python ]]; then
 echo '请按 README 安装 Python 依赖，或使用图枢网页.app。'
 read '?按回车退出'
 exit 1
fi
exec .venv/bin/python -m tushu.web.launcher "$@"

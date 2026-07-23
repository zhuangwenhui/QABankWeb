#!/usr/bin/env bash
# 新题发布后刷新自托管字体子集。
#
# 正文字体已内置 GB2312/JIS X0208 大兜底,绝大多数新题字形本就覆盖;仅当新题引入
# 兜底集外的生僻字才需要刷新。本脚本从生产库只读导出语料 → 重建子集 → 报告是否有变更。
# 幂等:无新字形则产物不变、git 无 diff、无需提交。
#
# 用法:scripts/refresh_fonts.sh
# 可选环境变量:QB_DEPLOY_KEY(默认 ~/.ssh/qbank_deploy)、QB_DEPLOY_HOST(默认 deploy@161.34.33.67)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="${QB_DEPLOY_KEY:-$HOME/.ssh/qbank_deploy}"
HOST="${QB_DEPLOY_HOST:-deploy@161.34.33.67}"
PY="$ROOT/.venv/bin/python"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

echo "[1/3] 从生产库只读导出语料(body 题面题解 / ui 元数据)…"
ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=15 "$HOST" 'python3 - <<PY
import sqlite3
c = sqlite3.connect("/srv/question-bank/instance/question_bank.db")
def dump(cols):
    return "".join("".join(filter(None, r)) for r in c.execute("SELECT %s FROM questions" % cols))
open("/tmp/_qb_body.txt", "w", encoding="utf-8").write(dump("question_latex,solution_latex,solution_ja"))
open("/tmp/_qb_ui.txt",   "w", encoding="utf-8").write(dump("source,subject,tags,chapter"))
print("exported")
PY'
scp -i "$KEY" -o BatchMode=yes "$HOST:/tmp/_qb_body.txt" "$TMP/body.txt"
scp -i "$KEY" -o BatchMode=yes "$HOST:/tmp/_qb_ui.txt"   "$TMP/ui.txt"
ssh -i "$KEY" -o BatchMode=yes "$HOST" 'rm -f /tmp/_qb_body.txt /tmp/_qb_ui.txt'

echo "[2/3] 重建字体子集(覆盖门会拦真缺字)…"
"$PY" "$ROOT/scripts/build_fonts.py" --body-corpus "$TMP/body.txt" --ui-corpus "$TMP/ui.txt"

echo "[3/3] 变更检查…"
cd "$ROOT"
if git diff --quiet -- static/fonts static/css/fonts.css; then
  echo "  ✓ 字体无变化(无新字形),无需提交。"
else
  echo "  ⚠ 字体有更新,请提交并部署:"
  git --no-pager diff --stat -- static/fonts static/css/fonts.css
  echo "    git add static/fonts static/css/fonts.css"
  echo "    git commit -m '字体排版:刷新字体子集(新题字形)'"
  echo "    然后按 docs/ops/deploy.md 推送 + gunicorn 重载。"
fi

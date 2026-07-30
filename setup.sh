#!/usr/bin/env bash
# 新闻台 GitHub Pages 一键初始化
# 用法: bash setup.sh <你的GitHub用户名> <仓库名>
# 前置: 1) 已在 github.com 注册并验证邮箱  2) 已把 SSH 公钥粘贴到 GitHub → Settings → SSH and GPG keys
set -e

if [ $# -lt 2 ]; then
  echo "用法: bash setup.sh <GitHub用户名> <仓库名>"
  echo "示例: bash setup.sh sherry newsdesk"
  exit 1
fi

USER="$1"
REPO="$2"
DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE="git@github.com:${USER}/${REPO}.git"
PY=$(command -v python3 || echo /usr/bin/python3)

echo "==> 工作目录: $DIR"
echo "==> 远程仓库: $REMOTE"

cd "$DIR"

# 1. 初始化 git（若未初始化）
if [ ! -d .git ]; then
  git init -q
  echo "[OK] git 仓库已初始化"
else
  echo "[跳过] 已是 git 仓库"
fi

# 2. 配置远程
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE"
  echo "[OK] 已更新 remote origin"
else
  git remote add origin "$REMOTE"
  echo "[OK] 已添加 remote origin"
fi

# 3. 确保主分支名为 main
git branch -M main

# 4. 首次生成新闻（确保 news.json 存在）
echo "==> 生成新闻数据..."
"$PY" update_news.py

# 5. 首次提交并推送
git add -A
git commit -q -m "init newsdesk" || echo "[跳过] 无新变更"
git push -u origin main

echo ""
echo "=========================================="
echo " 代码已推送到 GitHub"
echo " 下一步（网页操作）:"
echo "   1. 打开 https://github.com/${USER}/${REPO}"
echo "   2. Settings → Pages → Build and deployment"
echo "   3. Source 选 \"Deploy from a branch\""
echo "   4. Branch 选 main, 文件夹选 /(root)"
echo "   5. Save"
echo "   6. 约 1 分钟后访问:"
echo "      https://${USER}.github.io/${REPO}/financial-news-desk.html"
echo "=========================================="

# 6. 配置 crontab（每 3 小时自动更新并推送）
CRON_LINE="0 */3 * * * cd ${DIR} && ${PY} update_news.py >> /tmp/newsdesk.log 2>&1"
( crontab -l 2>/dev/null | grep -v "update_news.py" ; echo "$CRON_LINE" ) | crontab -
echo "[OK] crontab 已配置（每3小时自动更新并推送到 GitHub）"
echo "     查看: crontab -l   |   日志: tail -f /tmp/newsdesk.log"

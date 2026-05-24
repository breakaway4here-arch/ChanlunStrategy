#!/bin/zsh
# 缠论选股日报 — 自动运行并推送
# 由 launchd 每个工作日 14:35 触发

source ~/.zshrc 2>/dev/null || true
cd /Users/yangfan/yf_source/JQ_gu/chanlun_strategy

echo "=== 缠论选股日报 $(date '+%Y-%m-%d %H:%M:%S') ==="

/usr/bin/python3 run.py 2>&1

if [ $? -eq 0 ]; then
    git add docs/ data.json 2>/dev/null
    if ! git diff --cached --quiet; then
        git commit -m "chore: 自动更新 $(date '+%Y-%m-%d') 日报数据" 2>&1
        git push 2>&1
        echo "推送成功 $(date '+%H:%M:%S')"
    else
        echo "无数据变更，跳过推送"
    fi
else
    echo "run.py 执行失败，跳过推送"
fi

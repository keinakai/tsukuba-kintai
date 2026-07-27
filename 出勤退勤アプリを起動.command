#!/bin/bash
# アプリを起動します（毎回これをダブルクリック）
cd "$(dirname "$0")"

if [ -x "./.venv/bin/python" ]; then
  ./.venv/bin/python kintai_app.py
else
  echo "先に setup.command を実行してください。"
  read -n 1 -s -r -p "何かキーを押すと閉じます"
fi

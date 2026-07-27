#!/bin/bash
# 初回セットアップ（1回だけ実行）
# 専用の隔離環境(venv)を作り、その中に Playwright とブラウザを導入します。
# これで複数のPythonが混在していても確実に動きます。
cd "$(dirname "$0")"
APPDIR="$(pwd)"
VENV="$APPDIR/.venv"

echo "=============================================="
echo " 出退勤打刻アプリ セットアップ"
echo "=============================================="

# tkinter(GUI部品)が使える Python を探す（Homebrew版を優先）
BASE=""
for cand in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
            /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 \
            /usr/local/bin/python3 python3; do
  if "$cand" -c "import tkinter" >/dev/null 2>&1; then
    BASE="$cand"; break
  fi
done

if [ -z "$BASE" ]; then
  echo "❌ 画面表示に必要な tkinter 付きの Python が見つかりません。"
  echo "   ターミナルで  brew install python-tk@3.13  を実行してから、"
  echo "   もう一度この setup.command を実行してください。"
  read -n 1 -s -r -p "何かキーを押すと閉じます"
  exit 1
fi
echo "▶ 使用する Python: $BASE"

echo "▶ 専用環境(venv)を作成します…"
rm -rf "$VENV"
"$BASE" -m venv "$VENV"

echo "▶ Playwright とログイン情報保管用ライブラリを導入します…"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install playwright keyring

echo "▶ ブラウザ本体を導入します（導入済みなら再利用）…"
"$VENV/bin/python" -m playwright install chromium

# 動作確認
if "$VENV/bin/python" -c "import tkinter, playwright, keyring" >/dev/null 2>&1; then
  echo ""
  echo "✅ セットアップ完了。tkinter と Playwright の両方が使えます。"
  echo "   次回からは『出勤退勤アプリを起動.command』をダブルクリックしてください。"
else
  echo "⚠ 何かが不足しています。表示された内容をサポートに伝えてください。"
fi
read -n 1 -s -r -p "何かキーを押すと閉じます"

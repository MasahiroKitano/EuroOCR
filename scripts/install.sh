#!/bin/bash
# Copyright (c) 2026 Masahiro Kitano (北野雅弘)
# SPDX-License-Identifier: MIT
# EuroOCR ② セットアップ / setup
#   必要な部品をそろえ、スクリプトを ~/EuroOCR に置く。何度実行しても安全
#   （そろっている部品は飛ばす）。
#   Installs what EuroOCR needs and puts the scripts in ~/EuroOCR. Safe to re-run.
#
# 使い方 / usage:  bash install.sh [スクリプトのあるフォルダ / folder with the scripts]

set -u
SRC_DIR="${1:-$(cd "$(dirname "$0")" && pwd)}"
DEST="$HOME/EuroOCR"
LANGS="eng deu fra ita spa lat grc osd"
FAST_EXTRA="jpn"   # 日本語の本を見分けるための試し読み用 / to detect Japanese books
BEST_URL="https://github.com/tesseract-ocr/tessdata_best/raw/main"
FAST_URL="https://github.com/tesseract-ocr/tessdata_fast/raw/main"

if defaults read -g AppleLanguages 2>/dev/null | sed -n 2p | grep -q '"*ja'; then UI=ja; else UI=en; fi
say() { if [ "$UI" = ja ]; then echo "$1"; else echo "$2"; fi; }
step() { echo; say "▶ $1" "▶ $2"; }
fail() { echo; say "✖ $1" "✖ $2"; say "  このウインドウの内容を保存して、問題を確認してください。" \
                                      "  Please keep this window's output to check the problem."; exit 1; }

say "===== EuroOCR セットアップ =====" "===== EuroOCR setup ====="
say "保存先: $DEST" "Install folder: $DEST"

# ---- 1. Homebrew
step "Homebrew を確認します" "Checking Homebrew"
for p in /opt/homebrew /usr/local; do
  [ -x "$p/bin/brew" ] && eval "$("$p/bin/brew" shellenv)" && break
done
if ! command -v brew >/dev/null 2>&1; then
  say "Homebrew がないのでインストールします。Mac のパスワードを聞かれたら入力してください（画面には表示されません）。" \
      "Homebrew is missing; installing it. Enter your Mac password when asked (it is not shown)."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || fail "Homebrew のインストールに失敗しました" "Homebrew installation failed"
  for p in /opt/homebrew /usr/local; do
    [ -x "$p/bin/brew" ] && eval "$("$p/bin/brew" shellenv)" && break
  done
fi
command -v brew >/dev/null 2>&1 || fail "Homebrew が見つかりません" "Homebrew not found"
say "  OK: $(brew --prefix)" "  OK: $(brew --prefix)"

# ---- 2. 部品 / tools
step "OCRの部品を確認します（初回は時間がかかります）" "Checking OCR tools (first run takes a while)"
for f in tesseract ghostscript pngquant jbig2enc jbig2dec python@3.13 python-tk@3.13; do
  if brew list --formula "$f" >/dev/null 2>&1; then
    say "  済み: $f" "  present: $f"
  else
    say "  インストール: $f" "  installing: $f"
    brew install "$f" || fail "$f のインストールに失敗しました" "failed to install $f"
  fi
done

# ---- 3. Python の環境 / Python environment
step "Python の環境を用意します" "Preparing the Python environment"
mkdir -p "$DEST"
PY313="$(brew --prefix python@3.13)/bin/python3.13"
if [ ! -x "$DEST/venv/bin/python3" ]; then
  "$PY313" -m venv "$DEST/venv" || fail "Python の環境を作れませんでした" "could not create the Python environment"
fi
"$DEST/venv/bin/python3" -m pip install --quiet --upgrade pip
"$DEST/venv/bin/python3" -m pip install --quiet --upgrade ocrmypdf pikepdf pillow numpy opencv-python-headless \
  || fail "Python の部品を入れられませんでした" "could not install the Python packages"
say "  OK: ocrmypdf $("$DEST/venv/bin/python3" -m ocrmypdf --version 2>/dev/null)" \
    "  OK: ocrmypdf $("$DEST/venv/bin/python3" -m ocrmypdf --version 2>/dev/null)"

# ---- 4. 認識データ / language data
step "言語の認識データを確認します" "Checking language data"
mkdir -p "$DEST/tessdata_best" "$DEST/tessdata_fast"
fetch() {  # fetch フォルダ URL 言語
  local dir="$1" url="$2" l="$3"
  if [ -s "$dir/$l.traineddata" ]; then return 0; fi
  # 以前の GreekOCR で入れた best版があれば使い回す / reuse earlier GreekOCR data
  if [ "$dir" = "$DEST/tessdata_best" ] && [ -s "$HOME/GreekOCR/tessdata_best/$l.traineddata" ]; then
    cp "$HOME/GreekOCR/tessdata_best/$l.traineddata" "$dir/" && return 0
  fi
  curl -fsSL -o "$dir/$l.traineddata.part" "$url/$l.traineddata" \
    && mv "$dir/$l.traineddata.part" "$dir/$l.traineddata"
}
for l in $LANGS; do
  fetch "$DEST/tessdata_best" "$BEST_URL" "$l" || fail "best版 $l をダウンロードできませんでした" "could not download best $l"
done
say "  best版: $LANGS" "  best data: $LANGS"
for l in $LANGS $FAST_EXTRA; do
  fetch "$DEST/tessdata_fast" "$FAST_URL" "$l" || fail "通常版 $l をダウンロードできませんでした" "could not download fast $l"
done
say "  通常版（試し読み用）: $LANGS $FAST_EXTRA" "  fast data (for sampling): $LANGS $FAST_EXTRA"
STD="$(brew --prefix tesseract)/share/tessdata"
for d in tessdata_best tessdata_fast; do
  for sub in configs tessconfigs; do
    [ -e "$DEST/$d/$sub" ] || ln -s "$STD/$sub" "$DEST/$d/$sub"
  done
done

# ---- 5. スクリプト / scripts
step "スクリプトを置きます" "Installing the scripts"
for s in common.py spreads.py euro_ocr.py reocr_pages.py resplit.py install.sh; do
  if [ -f "$SRC_DIR/$s" ]; then
    cp "$SRC_DIR/$s" "$DEST/$s"
    say "  $s" "  $s"
  else
    fail "$SRC_DIR に $s がありません" "$s not found in $SRC_DIR"
  fi
done
mkdir -p "$DEST/logs"

# ---- 6. 確認 / check
step "動作を確認します" "Checking"
"$DEST/venv/bin/python3" -c "import pikepdf, cv2, numpy, PIL, ocrmypdf, tkinter" \
  || fail "Python の部品が読み込めません" "Python packages cannot be loaded"
TESSDATA_PREFIX="$DEST/tessdata_best" tesseract --list-langs 2>/dev/null | grep -qx grc \
  || fail "Tesseract が古典ギリシャ語のデータを読めません" "Tesseract cannot load the Greek data"
command -v gs >/dev/null || fail "Ghostscript が見つかりません" "Ghostscript not found"

echo
say "===== セットアップが完了しました =====" "===== Setup complete ====="
say "EuroOCR、EuroOCR-Pages、EuroOCR-Resplit のアプリが使えます。" "The EuroOCR, EuroOCR-Pages and EuroOCR-Resplit apps are ready."
osascript -e 'display notification "Setup complete / セットアップ完了" with title "EuroOCR" sound name "Glass"' >/dev/null 2>&1

#!/bin/bash
# Copyright (c) 2026 Masahiro Kitano (北野雅弘)
# SPDX-License-Identifier: MIT
# AppleScript の元ファイルから4つのアプリを作る
# Builds the four apps from the AppleScript sources
cd "$(dirname "$0")" || exit 1
for name in EuroOCR EuroOCR-Pages EuroOCR-Resplit EuroOCR-Setup; do
  rm -rf "$name.app"
  osacompile -o "$name.app" "$name.applescript" && echo "OK: $name.app" || echo "NG: $name.app"
done
echo
echo "完了しました。このウインドウは閉じてかまいません。 / Done. You can close this window."

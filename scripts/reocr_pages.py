#!/usr/bin/env python3
# Copyright (c) 2026 Masahiro Kitano (北野雅弘)
# SPDX-License-Identifier: MIT
"""
EuroOCR ③ 指定ページを指定した言語で読み直す（多言語の論集用）
         re-OCR chosen pages with chosen languages (for multilingual collections)

使い方 / usage:
  ~/EuroOCR/venv/bin/python3 ~/EuroOCR/reocr_pages.py 本_OCR.pdf --spec "1-40: deu; 41-85: fra+grc"

  指定の書き方 / spec format:
    「ページ: 言語」を ; か改行で区切る。ページは 5 / 5-12 / 5-12,20 のように書く。
    言語は eng deu fra ita spa lat grc を + でつなぐ。
    "pages: languages" separated by ; or newlines. Pages like 5 / 5-12 / 5-12,20.
    Languages: eng deu fra ita spa lat grc joined with +.

  画像には触れず、指定したページの文字の層だけを入れ替える。付箋などはそのまま残る。
  保存先: 同じフォルダに「元の名前_reOCR.pdf」（元のファイルは書き換えない）。
  元の名前がすでに _reOCR で終わる場合は、そのファイルを上書きする。
"""
import argparse
import datetime
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c          # noqa: E402
from common import T        # noqa: E402

import pikepdf              # noqa: E402

LOG_PATH = c.LOG_DIR / "EuroOCR_log.txt"


def parse_pages(text, npages):
    """'5-12,20' → 検証済みの文字列と、ページ番号の集合"""
    pages = set()
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(T(f"ページの書き方が正しくありません: {part}",
                               f"invalid page range: {part}"))
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if a < 1 or b < a or b > npages:
            raise ValueError(T(f"ページの範囲が正しくありません: {part}（全 {npages} ページ）",
                               f"page range out of bounds: {part} (document has {npages} pages)"))
        pages.update(range(a, b + 1))
    if not pages:
        raise ValueError(T("ページが指定されていません", "no pages given"))
    return pages


def parse_spec(spec, npages):
    """戻り値: [(ページの文字列, ページ集合, 言語リスト), ...]"""
    groups = []
    seen = set()
    # 日本語入力のまま打った全角の「：；＋、１２－」や「〜」も受け付ける
    spec = unicodedata.normalize("NFKC", spec)
    for ch in "〜~–—‐":
        spec = spec.replace(ch, "-")
    spec = spec.replace("、", ",")
    for chunk in re.split(r"[;\n]+", spec):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(T(f"「ページ: 言語」の形になっていません: {chunk}",
                               f"expected 'pages: languages': {chunk}"))
        ptext, ltext = chunk.split(":", 1)
        pages = parse_pages(ptext, npages)
        langs = [l for l in re.split(r"[+\s,]+", ltext.strip().lower()) if l]
        bad = [l for l in langs if l not in c.LANG_ORDER]
        if bad or not langs:
            raise ValueError(T(f"使えない言語: {', '.join(bad) or '（なし）'}（使えるのは "
                               f"{' '.join(c.LANG_ORDER)}）",
                               f"unknown language: {', '.join(bad) or '(none)'} (use "
                               f"{' '.join(c.LANG_ORDER)})"))
        dup = pages & seen
        if dup:
            raise ValueError(T(f"同じページが二度指定されています: {min(dup)} など",
                               f"page given twice: {min(dup)} and others"))
        seen |= pages
        groups.append((ptext.replace(" ", ""), pages, [l for l in c.LANG_ORDER if l in langs]))
    if not groups:
        raise ValueError(T("指定が空です", "empty spec"))
    return groups


def output_path(src):
    if src.stem.endswith("_reOCR"):
        return src
    return src.with_name(f"{src.stem}_reOCR.pdf")


def main():
    ap = argparse.ArgumentParser(description="EuroOCR: re-OCR chosen pages")
    ap.add_argument("file")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--jobs", default="4")
    a = ap.parse_args()

    src = Path(a.file).expanduser().resolve()
    if not (src.is_file() and src.suffix.lower() == ".pdf"):
        sys.exit(T(f"PDFファイルが見つかりません: {src}", f"PDF not found: {src}"))
    with pikepdf.open(src) as pdf:
        npages = len(pdf.pages)
    try:
        groups = parse_spec(a.spec, npages)
    except ValueError as e:
        c.notify(str(e))
        sys.exit(T(f"指定に誤りがあります: {e}", f"Spec error: {e}"))

    dst = output_path(src)
    print(T(f"===== EuroOCR 指定ページの読み直し：{src.name}（全 {npages} ページ） =====",
            f"===== EuroOCR re-OCR pages: {src.name} ({npages} pages) ====="), flush=True)
    tmp = Path(tempfile.mkdtemp(prefix="eurocr_pages_"))
    start = time.time()
    c.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_PATH, "a", encoding="utf-8")
    log.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M} re-OCR {src} =====\n")
    try:
        current = tmp / "step0.pdf"
        c.strip_annots(src, current)          # 注釈は最後に元から移植する
        for i, (ptext, pages, langs) in enumerate(groups, 1):
            lang = "+".join(langs)
            data = c.choose_tessdata(langs)
            print(T(f"\n[{i}/{len(groups)}] {ptext} ページ → {lang}（{data}）",
                    f"\n[{i}/{len(groups)}] pages {ptext} → {lang} ({data})"), flush=True)
            nxt = tmp / f"step{i}.pdf"
            common = ["--output-type", "pdf", "-l", lang, "--jobs", a.jobs, "--pages", ptext]
            try:
                c.ocrmypdf("--mode", "redo", *common, current, nxt)
                how = T("文字の層を入れ替え", "text layer replaced")
            except RuntimeError as e:
                # 見える文字（ClearScan など）があって入れ替えられないページは作り直す
                print(T("    文字の層を入れ替えられないため、ページを作り直します",
                        "    cannot replace the text layer; rebuilding these pages"), flush=True)
                c.ocrmypdf("--mode", "force", *common, current, nxt)
                how = T("ページを作り直し", "pages rebuilt")
            print(f"    OK（{how}）" if c.UI == "ja" else f"    OK ({how})", flush=True)
            log.write(f"  {ptext}: {lang} | {data} | {how}\n")
            current = nxt
        final = tmp / "final.pdf"
        c.copy_annots(src, current, final)
        shutil.move(str(final), str(dst))
        mins = (time.time() - start) / 60
        summary = T(f"完了: {dst.name}（{mins:.1f}分）", f"Done: {dst.name} ({mins:.1f} min)")
        log.write(f"OK   {dst}\n")
    except Exception as e:
        summary = T(f"失敗: {src.name}", f"Failed: {src.name}")
        print(f"\n{e}", flush=True)
        log.write(f"FAIL {src} | {e}".replace("\n", " / ") + "\n")
    finally:
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n===== {summary} =====", flush=True)
    c.notify(summary)


if __name__ == "__main__":
    main()

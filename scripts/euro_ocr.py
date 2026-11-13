#!/usr/bin/env python3
# Copyright (c) 2026 Masahiro Kitano (北野雅弘)
# SPDX-License-Identifier: MIT
"""
EuroOCR ① 1冊ずつOCR / one book at a time

  見開きの分割 → ノイズ除去 → 傾き補正 → 言語判定（必要なら確認）→ OCR
  英・独・仏・伊・西・ラテン・古典ギリシャ語に対応。
  保存先: 元のファイルと同じフォルダに「元の名前_OCR.pdf」（元のファイルは書き換えない）

使い方 / usage:
  ~/EuroOCR/venv/bin/python3 ~/EuroOCR/euro_ocr.py 本1.pdf 本2.pdf ...
      --ask-always   全冊で言語の確認画面を出す / always confirm languages
      --check        判定だけ表示して何も作らない / analyze only
      --no-clean     ノイズ除去をしない / skip despeckling
      --no-deskew    傾き補正をしない / skip deskewing
      --jobs 4       OCRに使うCPUコア数 / CPU cores for OCR
      --greek        ギリシャ語を必ず加える / always include Ancient Greek
      --force        強制OCR: 種類に関係なく全ページ作り直す（日本語中心の本は除く）
                     / rebuild every page regardless of type (except Japanese books)
      --auto-gutter  試験的: ノドの位置の自動補正 / experimental gutter detection
"""
import argparse
import datetime
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c          # noqa: E402
from common import T        # noqa: E402
import spreads as sp        # noqa: E402

import pikepdf              # noqa: E402

LOG_PATH = c.LOG_DIR / "EuroOCR_log.txt"
ALL_LANGS = "+".join(c.LANG_ORDER)
SPREAD_SHARE = 0.5                               # 横長のページがこの割合以上なら見開きの本
SAMPLE_FRACTIONS = (0.2, 0.35, 0.5, 0.65, 0.8)   # 試し読みするページの位置
DESPECKLE_AREA = 6                               # これより小さい黒い点を消す（ピクセル）


def say(msg=""):
    print(msg, flush=True)


def maybe_split(src, tmpdir, auto_gutter=False):
    """見開きの本なら分割した一時ファイルを返す。戻り値: (作業用ファイル, 説明)"""
    with pikepdf.open(src) as pdf:
        n = len(pdf.pages)
        wide = sum(1 for p in pdf.pages if sp.is_spread(p))
    if n == 0 or wide < n * SPREAD_SHARE:
        return src, ""
    out = Path(tmpdir) / "split.pdf"
    n0, nsplit, after, notes = sp.split_pdf(src, out, rtl=False, gutter=0.5,
                                            keep_first=0, keep_last=0, auto_gutter=auto_gutter)
    if not out.exists():
        return src, ""
    desc = T(f"見開き {nsplit}ページを分割（{n0}→{after}ページ）",
             f"split {nsplit} spreads ({n0}→{after} pages)")
    try:
        dropped, _ = sp.drop_blank_first(out)
        if dropped:
            desc += T("、白紙の1ページ目を削除", ", removed blank first page")
    except Exception as e:
        desc += T(f"（白紙の判定ができず1ページ目は残しました: {e}）",
                  f" (blank check failed, kept page 1: {e})")
    for note in notes:
        desc += f" / {note}"
    return out, desc


def detect_languages(path, npages, cat, always_greek=False):
    text_layer = "" if cat == "scan" else c.extract_text(path, npages)
    fractions = SAMPLE_FRACTIONS if npages > len(SAMPLE_FRACTIONS) else (0.5,)
    data_dir = c.FAST_DIR if all((c.FAST_DIR / f"{l}.traineddata").exists()
                                 for l in c.LANG_ORDER) else None
    sample = c.ocr_sample(path, npages, ALL_LANGS, fractions, data_dir=data_dir)
    counts = c.word_counts(text_layer + "\n" + sample)
    greek, _ = c.greek_letters(sample)   # 古い文字層のギリシャ語は化けているので数えない
    langs, sure, reasons = c.judge(counts, greek)
    if always_greek:
        # ギリシャ語は指定で必ず加えるので、ギリシャ文字の多い少ないでは迷わない
        reasons = [r for r in reasons if not r.startswith(("ギリシャ文字", "only a few Greek"))]
        if "grc" not in langs:
            langs = [l for l in c.LANG_ORDER if l in langs + ["grc"]]
        sure = not reasons
    short = {"eng": ("英", "en"), "deu": ("独", "de"), "fra": ("仏", "fr"), "ita": ("伊", "it"),
             "spa": ("西", "es"), "lat": ("羅", "la")}
    detail = (T("よく出る単語 ", "common words ")
              + " ".join(f"{T(*short[l])}{counts.get(l, 0)}" for l in short)
              + T(f" ／ ギリシャ文字 {greek}字", f" / Greek letters {greek}"))
    return langs, sure, reasons, detail


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def ask_languages(name, langs, reasons, detail, desc):
    """言語を選ぶ画面。戻り値: 言語のリスト、または None（この本は飛ばす）"""
    items = [f"{c.lang_name(l)} ({l})" for l in c.LANG_ORDER]
    defaults = [f"{c.lang_name(l)} ({l})" for l in langs]
    prompt = f"{name}\n\n{T('判定', 'Detected')}: {detail}"
    if desc:
        prompt += f"\n{desc}"
    if reasons:
        prompt += "\n" + T("迷った点: ", "Uncertain: ") + " / ".join(reasons)
    prompt += "\n\n" + T("OCRに使う言語を選んでください（⌘クリックで複数選択）。",
                         "Choose the OCR languages (⌘-click for several).")
    script = (
        'tell application "Terminal"\nactivate\n'
        f"set r to choose from list {{{', '.join(q(i) for i in items)}}} "
        f"with title {q(T('EuroOCR：言語の確認', 'EuroOCR: languages'))} with prompt {q(prompt)} "
        f"default items {{{', '.join(q(i) for i in defaults)}}} "
        f"OK button name {q(T('この言語でOCR', 'OCR'))} "
        f"cancel button name {q(T('この本は飛ばす', 'Skip this book'))} "
        "with multiple selections allowed\nend tell\n"
        'if r is false then return "SKIP"\n'
        "set AppleScript's text item delimiters to linefeed\nreturn r as text")
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    out = r.stdout.strip()
    if r.returncode != 0 or out == "SKIP" or not out:
        return None
    chosen = re.findall(r"\((\w{3})\)", out)
    return [l for l in c.LANG_ORDER if l in chosen] or None


def run_ocr(work, info, cat, lang, dst, jobs, clean, deskew):
    """work（元ファイルか分割後の一時ファイル）をOCRして dst に保存。戻り値: 補足の説明"""
    common = ["--output-type", "pdf", "-l", lang, "--jobs", jobs]
    tmp = Path(tempfile.mkdtemp(prefix="eurocr_ocr_"))
    extra = []
    try:
        final = tmp / "final.pdf"
        if cat == "redo":
            # 文字の層だけ入れ替える（画像には触れないので、ノイズ除去・傾き補正はしない）
            c.ocrmypdf("--mode", "redo", *common, work, final)
        else:
            source = tmp / "clean.pdf"
            c.strip_annots(work, source)          # 注釈は最後に元から移植する
            is_scan = cat in ("scan", "scanocr")
            if is_scan and clean and info["any_bilevel"]:
                cleaned, removed = c.despeckle_pdf(source, tmp / "despeckled.pdf", DESPECKLE_AREA)
                source = tmp / "despeckled.pdf"
                extra.append(T(f"ノイズ除去 {removed}点", f"despeckled {removed} dots"))
            ocr = tmp / "ocr.pdf"
            if cat == "scan":
                args = ["--mode", "skip", "--optimize", "3"]
            else:  # ClearScan / FineReader / 現代ギリシャ語として認識済み / 文字入りスキャン
                args = ["--mode", "force", "--optimize", "3"]
            if is_scan and deskew:
                args.append("--deskew")
                extra.append(T("傾き補正", "deskewed"))
            c.ocrmypdf(*args, *common, source, ocr)
            current = ocr
            # 元が白黒2値なら、白黒に戻して軽くする
            if info["all_bilevel"] or not info["has_images"]:
                bw = tmp / "bw.pdf"
                if c.binarize(ocr, bw) > 0:
                    bwopt = tmp / "bwopt.pdf"
                    c.ocrmypdf("--mode", "skip", "--optimize", "3", *common, bw, bwopt)
                    current = bwopt
            c.copy_annots(work, current, final)
        shutil.move(str(final), str(dst))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ", ".join(extra)


def output_path(src):
    return src.with_name(f"{src.stem}_OCR.pdf")


def analyze(plan, ask_always, check_only):
    src = plan["src"]
    dst = output_path(src)
    if dst.exists() and not check_only:
        plan["skip"] = T(f"結果がすでにあります（{dst.name}）", f"result already exists ({dst.name})")
        return
    work, desc = maybe_split(src, plan["tmpdir"], plan.get("auto_gutter", False))
    plan.update(work=work, split_desc=desc)
    cat, info, npages = c.decide(work)
    if plan.get("force") and cat != "japanese":
        cat = "forced"            # 日本語中心の本は強制OCRでも処理しない
    plan.update(cat=cat, info=info, npages=npages)
    if cat in ("japanese", "digital"):
        plan["skip"] = c.category_name(cat)
        return
    langs, sure, reasons, detail = detect_languages(work, npages, cat, plan.get("greek", False))
    plan.update(langs=langs, sure=sure, reasons=reasons, detail=detail)
    if check_only:
        return
    if ask_always or not sure:
        chosen = ask_languages(src.name, langs, reasons, detail, desc)
        if chosen is None:
            plan["skip"] = T("確認画面で「飛ばす」が選ばれました", "skipped in the dialog")
            return
        plan["langs"] = chosen
        plan["confirmed"] = True


def main():
    ap = argparse.ArgumentParser(description="EuroOCR: one book at a time")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--ask-always", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-clean", action="store_true")
    ap.add_argument("--no-deskew", action="store_true")
    ap.add_argument("--jobs", default="4")
    ap.add_argument("--greek", action="store_true", help="ギリシャ語を必ず加える")
    ap.add_argument("--force", action="store_true", help="強制OCR（全ページ作り直す）")
    ap.add_argument("--auto-gutter", action="store_true",
                    help="試験的: 文字にかかる見開きだけノドの位置をずらして切る")
    a = ap.parse_args()

    files, ignored = [], []
    for f in a.files:
        p = Path(f).expanduser().resolve()
        if p in files:
            continue
        if p.is_file() and p.suffix.lower() == ".pdf" and not p.stem.endswith("_OCR"):
            files.append(p)
        else:
            ignored.append(p.name + (T("（フォルダ）", " (folder)") if p.is_dir() else
                                     T("（OCR済み）", " (already OCR)") if p.stem.endswith("_OCR")
                                     else ""))

    say(T(f"===== EuroOCR：{len(files)} 冊 =====", f"===== EuroOCR: {len(files)} book(s) ====="))
    if ignored:
        say(T("対象外のため飛ばします: ", "Ignored: ") + ", ".join(ignored))
    opts = [x for x, on in ((T("ギリシャ語を必ず加える", "always include Greek"), a.greek),
                            (T("強制OCR", "forced OCR"), a.force),
                            (T("全冊で言語を確認", "confirm languages for every book"), a.ask_always)) if on]
    if opts:
        say(T("指定: ", "Options: ") + ", ".join(opts))

    # 第1段階：全冊を調べ、必要なら確認する
    plans = []
    for i, src in enumerate(files, 1):
        say(T(f"\n[{i}/{len(files)}] 調べています: {src.name}",
              f"\n[{i}/{len(files)}] Analyzing: {src.name}"))
        plan = {"src": src, "tmpdir": tempfile.mkdtemp(prefix="eurocr_plan_"), "skip": None,
                "auto_gutter": a.auto_gutter, "greek": a.greek, "force": a.force}
        try:
            analyze(plan, a.ask_always, a.check)
        except Exception as e:
            plan["skip"] = T(f"調べる途中で失敗: {e}", f"analysis failed: {e}")
        if plan.get("split_desc"):
            say(f"    {plan['split_desc']}")
        if plan.get("cat"):
            say(T(f"    種類: {c.category_name(plan['cat'])} ／ {plan['npages']}ページ",
                  f"    Type: {c.category_name(plan['cat'])} / {plan['npages']} pages"))
        if plan.get("detail"):
            say(f"    {T('判定', 'Detected')}: {plan['detail']}")
            mark = (T("（確認済み）", "(confirmed)") if plan.get("confirmed")
                    else "" if plan["sure"] else T("（自信なし）", "(uncertain)"))
            say(f"    {T('言語', 'Languages')}: {'+'.join(plan['langs'])} {mark}")
            for r in plan.get("reasons", []):
                say(f"    {T('迷った点', 'Uncertain')}: {r}")
        if plan["skip"]:
            say(f"    → {plan['skip']}")
        plans.append(plan)

    if a.check:
        for p in plans:
            shutil.rmtree(p["tmpdir"], ignore_errors=True)
        return

    # 第2段階：続けてOCRする
    todo = [p for p in plans if not p["skip"]]
    say(T(f"\n===== 判定が済みました。{len(todo)} 冊をOCRします（あとは操作不要） =====",
          f"\n===== Analysis done. OCR of {len(todo)} book(s) starts (no further input needed) ====="))
    c.LOG_DIR.mkdir(parents=True, exist_ok=True)
    done = failed = 0
    start = time.time()
    with open(LOG_PATH, "a", encoding="utf-8") as log:
        log.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M} =====\n")
        for p in plans:
            if p["skip"]:
                log.write(f"SKIP {p['src']} | {p['skip']}\n")
        for i, p in enumerate(todo, 1):
            src, dst = p["src"], output_path(p["src"])
            lang = "+".join(p["langs"])
            data = c.choose_tessdata(p["langs"])
            say(f"\n[{i}/{len(todo)}] OCR: {src.name}\n    {c.category_name(p['cat'])} / "
                f"{lang} / {data}")
            t0 = time.time()
            try:
                extra = run_ocr(p["work"], p["info"], p["cat"], lang, dst, a.jobs,
                                not a.no_clean, not a.no_deskew)
                notes = " | ".join(x for x in (p.get("split_desc"), extra) if x) or "-"
                line = (f"OK   {src} | {p['npages']}p | {lang} | {data} | {notes} | "
                        f"{c.mb(src):.1f}MB→{c.mb(dst):.1f}MB | {(time.time() - t0) / 60:.1f}min")
                done += 1
            except KeyboardInterrupt:
                log.write(f"STOP {src}\n")
                say(T("\n中断しました。", "\nStopped."))
                break
            except Exception as e:
                line = f"FAIL {src} | {e}".replace("\n", " / ")
                failed += 1
            finally:
                shutil.rmtree(p["tmpdir"], ignore_errors=True)
            say("    " + line)
            log.write(line + "\n")
            log.flush()
        skipped = len(plans) - len(todo)
        mins = (time.time() - start) / 60
        summary = T(f"終了: 成功 {done} / 失敗 {failed} / 飛ばし {skipped} / {mins:.0f}分",
                    f"Done: {done} OK / {failed} failed / {skipped} skipped / {mins:.0f} min")
        log.write(summary + "\n")
    for p in plans:
        shutil.rmtree(p["tmpdir"], ignore_errors=True)
    say(f"\n===== {summary} =====\n" + T(f"ログ: {LOG_PATH}", f"Log: {LOG_PATH}"))
    c.notify(summary)


if __name__ == "__main__":
    main()

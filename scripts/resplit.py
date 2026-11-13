#!/usr/bin/env python3
# Copyright (c) 2026 Masahiro Kitano (北野雅弘)
# SPDX-License-Identifier: MIT
"""
EuroOCR ④ 分割の切り直し / re-split a page pair

  見開きの分割がずれて文字が切れているページを見つけたとき:
   1. そのページを含む元の見開きを表示する（同じフォルダの元のスキャンから）
   2. 粗い画像の上で、切る位置をクリックで選ぶ
   3. 元の見開きを新しい位置で切り、その2ページだけをノイズ除去・傾き補正・OCRし直す
  元のファイルが見つからないときは、OCR済みの2ページをくっつけ直して切る（このときは
  最初のOCRの傾き補正のため、行がわずかにずれることがある）。
  ファイルは上書き保存する（上書き前の版は ~/EuroOCR/backup に残す）。
  付箋・ハイライトは位置に応じて左右のページに振り分け直す。

  When a split page cuts through text: rejoin it with the next page, click the new cut
  position on a preview, and re-OCR just those two pages. The file is overwritten
  (the previous version is kept in ~/EuroOCR/backup).

使い方 / usage:
  ~/EuroOCR/venv/bin/python3 ~/EuroOCR/resplit.py 本_OCR.pdf
"""
import datetime
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c          # noqa: E402
from common import T        # noqa: E402
import spreads as sp        # noqa: E402

import pikepdf              # noqa: E402
from pikepdf import Name, Array, Dictionary   # noqa: E402

BACKUP_DIR = c.HOME_DIR / "backup"
BACKUP_KEEP = 30            # バックアップを残す数
LOG_PATH = c.LOG_DIR / "EuroOCR_log.txt"


# ---------------------------------------------------------------- PDFの加工

def page_box(page):
    box = page.obj.get(Name.CropBox, page.obj.MediaBox)
    x0, y0, x1, y1 = (float(v) for v in box)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def pair_widths(pdf_path, n):
    """n ページ目（0始まり）と次のページの幅と高さ"""
    with pikepdf.open(pdf_path) as pdf:
        a, b = page_box(pdf.pages[n]), page_box(pdf.pages[n + 1])
    return a[2] - a[0], b[2] - b[0], max(a[3] - a[1], b[3] - b[1])


def shift_annot(a, dx, dy, dst):
    """注釈を (dx, dy) だけ動かした複製を返す"""
    na = dst.make_indirect(Dictionary(a))

    def shift(arr):
        return Array([float(v) + (dx if i % 2 == 0 else dy) for i, v in enumerate(arr)])

    na.Rect = shift(a.Rect)
    for key in (Name.QuadPoints, Name.Vertices, Name.L):
        if key in na:
            na[key] = shift(na[key])
    if Name.InkList in na:
        na.InkList = Array([shift(s) for s in na.InkList])
    for key in (Name.Popup, Name.P):
        if key in na:
            del na[key]
    return na


SEAM_BAND_PT = 12          # つなぎ目のすぐ左右、この幅（ポイント）で行の並びを比べる
SEAM_MAX_PT = 8            # 上下にずらす量の上限（ポイント。半行ほど）


def seam_offset(src, n, dpi=150):
    """OCR済みの n ページ目と次のページのつなぎ目で、行がぴったり重なるように
    右ページを上下にずらす量（ポイント、上が正）を求める。
    左右のページを別々に傾き補正したときにできる、つなぎ目の段差を打ち消すため。
    行の並びがはっきりしないときは 0"""
    import numpy as np
    from PIL import Image
    tmp = Path(tempfile.mkdtemp(prefix="eurocr_seam_"))
    try:
        arrs = []
        for i in (n, n + 1):
            png = tmp / f"p{i}.png"
            subprocess.run([c.find_tool("gs"), "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
                            "-sDEVICE=pnggray", f"-r{dpi}", f"-dFirstPage={i + 1}",
                            f"-dLastPage={i + 1}", f"-sOutputFile={png}", str(src)],
                           capture_output=True, timeout=120)
            arrs.append(np.array(Image.open(png).convert("L")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    left, right = arrs
    band = int(SEAM_BAND_PT * dpi / 72)
    h = min(left.shape[0], right.shape[0])
    pl = (left[:h, -band:] < 128).sum(axis=1).astype(float)
    pr = (right[:h, :band] < 128).sum(axis=1).astype(float)
    m = int(h * 0.03)
    pl[:m] = pl[-m:] = 0
    pr[:m] = pr[-m:] = 0
    if pl.sum() < band * 2 or pr.sum() < band * 2:
        return 0.0                       # どちらかにほとんど文字がない
    limit = int(SEAM_MAX_PT * dpi / 72)
    best, best_s, at_zero = -1.0, 0, 0.0
    for s in range(-limit, limit + 1):
        a = pl[max(0, -s):h - max(0, s)]
        b = pr[max(0, s):h - max(0, -s)]
        if a.std() == 0 or b.std() == 0:
            continue
        score = float(np.corrcoef(a, b)[0, 1])
        if s == 0:
            at_zero = score
        if score > best:
            best, best_s = score, s
    if best < 0.4 or best - at_zero < 0.05:
        return 0.0                       # はっきり合う位置がない、またはずれていない
    return best_s * 72 / dpi             # 右の行 y+s が左の行 y に当たる → 右を上へ s


def rejoin_in(pdf, n, cut_x, dy=0.0):
    """開いている pdf の n ページ目と次のページを横に並べて1枚にし、左端から cut_x
    （ポイント）の位置で切り直して2ページに戻す。画像は切らない（表示範囲だけ）"""
    left, right = pdf.pages[n], pdf.pages[n + 1]
    lx0, ly0, lx1, ly1 = page_box(left)
    rx0, ry0, rx1, ry1 = page_box(right)
    wl, wr = lx1 - lx0, rx1 - rx0
    h = max(ly1 - ly0, ry1 - ry0)
    if not (0 < cut_x < wl + wr):
        raise ValueError(T("切る位置が範囲の外です", "cut position out of range"))

    # 2ページをそれぞれフォーム（部品）にして、横に並べた見開きを作る
    fl = left.as_form_xobject()
    fr = right.as_form_xobject()
    joined_content = pdf.make_stream(
        (f"q 1 0 0 1 {-lx0:.4f} {-ly0:.4f} cm /EuroL Do Q\n"
         f"q 1 0 0 1 {wl - rx0:.4f} {-ry0 + dy:.4f} cm /EuroR Do Q\n").encode())
    resources = Dictionary(XObject=Dictionary(EuroL=fl, EuroR=fr))

    # 注釈は見開きの座標に直して集める
    annots = Array()
    for page, ax, ay in ((left, -lx0, -ly0), (right, wl - rx0, -ry0 + dy)):
        for a in page.obj.get(Name.Annots, []):
            if Name.Rect in a and a.get(Name.Subtype) != Name.Popup:
                annots.append(shift_annot(a, ax, ay, pdf))

    halves = []
    for x_from, x_to in ((0.0, cut_x), (cut_x, wl + wr)):
        cm = pdf.make_stream(f"1 0 0 1 {-x_from:.4f} 0 cm\n".encode())
        page_dict = Dictionary(Type=Name.Page, MediaBox=Array([0, 0, x_to - x_from, h]),
                               Resources=resources, Contents=Array([cm, joined_content]))
        if len(annots):
            page_dict.Annots = Array(list(annots))
        halves.append({"page": pikepdf.Page(pdf.make_indirect(page_dict)),
                       "x_from": x_from, "x_to": x_to})
    sp.split_annots(halves, pdf)

    # 元の2ページを新しい2ページに置き換える
    del pdf.pages[n + 1]
    del pdf.pages[n]
    pdf.pages.insert(n, halves[0]["page"])
    pdf.pages.insert(n + 1, halves[1]["page"])


def rejoin_and_cut(src, dst, n, cut_x, dy=0.0):
    """rejoin_in をファイルに対して行い、dst に保存する"""
    with pikepdf.open(src) as pdf:
        rejoin_in(pdf, n, cut_x, dy)
        pdf.save(dst)


def bilevel_pages(pdf_path, idxs):
    """指定したページの画像がすべて白黒2値か"""
    with pikepdf.open(pdf_path) as pdf:
        bits = set()
        for i in idxs:
            for img in c.page_images(pdf.pages[i]):
                bits.add(1 if img.get(Name.ImageMask, False) else int(img.get(Name.BitsPerComponent, 8)))
    return bool(bits) and bits <= {1}


def binarize_pages(src, dst, idxs, threshold=140):
    """指定したページの画像だけを白黒2値にする"""
    import zlib
    from pikepdf import PdfImage
    n = 0
    with pikepdf.open(src) as pdf:
        for i in idxs:
            for raw in c.page_images(pdf.pages[i]):
                if raw.get(Name.BitsPerComponent) == 1 or raw.get(Name.ImageMask, False):
                    continue
                pil = PdfImage(raw).as_pil_image().convert("L")
                bw = pil.point(lambda v: 255 if v > threshold else 0).convert("1", dither=0)
                for key in (Name.DecodeParms, Name.Decode, Name.SMask):
                    if key in raw:
                        del raw[key]
                raw.write(zlib.compress(bw.tobytes()), filter=Name.FlateDecode)
                raw.ColorSpace = Name.DeviceGray
                raw.BitsPerComponent = 1
                n += 1
        pdf.save(dst)
    return n


def backup(src):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = BACKUP_DIR / f"{src.stem}__{stamp}{src.suffix}"
    shutil.copy2(src, dst)
    old = sorted(BACKUP_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime)
    for p in old[:-BACKUP_KEEP]:
        p.unlink(missing_ok=True)
    return dst


def guess_langs(src, n):
    """2ページの今の文字から言語を推定する（初期値用）"""
    text = c.extract_text(src, n + 2, first=n + 1, span=2)
    langs, _, _ = c.judge(c.word_counts(text), c.greek_letters(text)[0])
    if len(langs) == len(c.LANG_ORDER):          # 判定できなかった
        return ["eng"]
    return langs


def render_parts(src, n, height_px=760):
    """2ページをそれぞれ画像にする。戻り値: (左の画像, 右の画像, ポイント→ピクセルの倍率, 左ページの幅)"""
    from PIL import Image
    wl, wr, h = pair_widths(src, n)
    dpi = max(20, min(150, height_px / (h / 72)))
    tmp = Path(tempfile.mkdtemp(prefix="eurocr_prev_"))
    try:
        ims = []
        for i in (n, n + 1):
            png = tmp / f"p{i}.png"
            subprocess.run([c.find_tool("gs"), "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
                            "-sDEVICE=png16m", f"-r{dpi:.1f}", f"-dFirstPage={i + 1}",
                            f"-dLastPage={i + 1}", f"-sOutputFile={png}", str(src)],
                           capture_output=True, timeout=120)
            ims.append(Image.open(png).convert("RGB"))
        return ims[0], ims[1], dpi / 72, wl
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def compose(left_im, right_im, scale, wl, dy=0.0):
    """2ページの画像を横に並べる。右ページは dy ポイントだけ上にずらす"""
    from PIL import Image
    x = int(round(wl * scale))
    W = x + right_im.width
    H = max(left_im.height, right_im.height)
    joined = Image.new("RGB", (W, H), "white")
    joined.paste(left_im, (0, 0))
    joined.paste(right_im, (x, int(round(-dy * scale))))
    return joined


def render_pair(src, n, height_px=760, dy=0.0):
    """2ページを横に並べたプレビュー画像（PIL）と、倍率、左ページの幅を返す"""
    left_im, right_im, scale, wl = render_parts(src, n, height_px)
    return compose(left_im, right_im, scale, wl, dy), scale, wl


# ---------------------------------------------------------------- 元のスキャンから切り直す

SPREAD_SHARE = 0.5          # euro_ocr.py と同じ基準（横長のページがこの割合以上なら見開きの本）


def find_original(src):
    """OCR済みファイルの隣にある元のファイル（名前から _OCR などを除いたもの）"""
    src = Path(src)
    stem = src.stem
    for suffix in ("_reOCR", "_OCR"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    if stem == src.stem:
        return None
    for ext in (".pdf", ".PDF"):
        cand = src.with_name(stem + ext)
        if cand.exists():
            return cand
    return None


def build_map(orig, ocr_npages):
    """EuroOCR の分割を元のファイルで再現し、OCR済みファイルの各ページが
    元の何ページ目のどちら側かを返す: [(元のページ番号, "L"/"R"/"W"), ...]
    再現できなければ None"""
    with pikepdf.open(orig) as pdf:
        n = len(pdf.pages)
        wide = [sp.is_spread(p) for p in pdf.pages]
    split = n > 0 and sum(1 for p in wide if p) >= n * SPREAD_SHARE
    mapping = []
    for k in range(n):
        if split and wide[k]:
            mapping += [(k, "L"), (k, "R")]
        else:
            mapping.append((k, "W"))
    if len(mapping) == ocr_npages + 1 and mapping[0][1] == "L":
        mapping = mapping[1:]                 # 白紙の1ページ目が削除されていた
    if len(mapping) != ocr_npages:
        return None
    return mapping


def spread_pair(mapping, n):
    """OCR済みファイルの n ページ目を含む見開きの (元のページ番号, 左ページ番号, 右ページ番号)。
    左右がそろわない（見開きでない、白紙削除で片方しかない）ときは None"""
    k, side = mapping[n]
    if side == "W":
        return None
    try:
        left = mapping.index((k, "L"))
        right = mapping.index((k, "R"))
    except ValueError:
        return None
    return k, left, right


def recut_in(pdf, o, k, left, right, cut_x):
    """開いている元のファイル o の k ページ目（見開き）を cut_x で切った2ページで、
    開いている OCR済みファイル pdf の left・right ページを置き換える。注釈は振り分け直す"""
    spread = o.pages[k]
    _, spread_w, _ = sp.display_transform(spread)       # 回転指定を反映した見た目の幅
    if not (0 < cut_x < spread_w):
        raise ValueError(T("切る位置が範囲の外です", "cut position out of range"))
    # 今の注釈を見開きの座標で集める（右ページは今の切れ目の分だけ右へ）
    old_cut = page_box(pdf.pages[left])[2] - page_box(pdf.pages[left])[0]
    annots = []
    for idx, dx in ((left, 0.0), (right, old_cut)):
        page = pdf.pages[idx]
        bx0, by0, _, _ = page_box(page)
        for a in page.obj.get(Name.Annots, []):
            if Name.Rect in a and a.get(Name.Subtype) != Name.Popup:
                annots.append(shift_annot(a, dx - bx0, -by0, pdf))
    # 元の見開きを新しい位置で切った2ページを作る
    tmp = pikepdf.new()
    sp.make_half(tmp, spread, 0.0, cut_x)
    sp.make_half(tmp, spread, cut_x, spread_w)
    for p in tmp.pages:
        if Name.Annots in p.obj:
            del p.obj[Name.Annots]
    pdf.pages[left] = tmp.pages[0]
    pdf.pages[right] = tmp.pages[1]
    halves = [{"page": pdf.pages[left], "x_from": 0.0, "x_to": cut_x},
              {"page": pdf.pages[right], "x_from": cut_x, "x_to": spread_w}]
    if annots:
        for h in halves:
            h["page"].obj.Annots = Array(annots)
        sp.split_annots(halves, pdf)


def recut_from_original(src, orig, dst, k, left, right, cut_x):
    """recut_in をファイルに対して行い、dst に保存する"""
    with pikepdf.open(src) as pdf, pikepdf.open(orig) as o:
        recut_in(pdf, o, k, left, right, cut_x)
        pdf.save(dst)


def page_spec(pairs):
    """[(left, right), ...]（0始まり）→ OCRmyPDF の --pages の指定（1始まり）"""
    return ",".join(f"{l + 1}-{r + 1}" for l, r in sorted(pairs))


def resplit_many(src, edits, orig=None, jobs="4", progress=print, despeckle_area=6):
    """切り直しの予定 edits をまとめて行い、上書き保存する。戻り値: バックアップの場所
    edits: [{"left", "right", "cut_x", "langs", "k"(元のファイルの見開き), "dy"(くっつけるとき)}]
    orig があれば元のスキャンから切り直し（新しいページにノイズ除去・傾き補正・OCR）、
    なければ OCR済みの2ページをくっつけて切り直す（2ページを作り直して OCR）"""
    src = Path(src)
    edits = sorted(edits, key=lambda e: e["left"])
    tmp = Path(tempfile.mkdtemp(prefix="eurocr_resplit_"))
    try:
        progress(T(f"{len(edits)}か所を切り直しています…", f"Re-cutting {len(edits)} spread(s)…"))
        cut = tmp / "cut.pdf"
        with pikepdf.open(src) as pdf:
            if orig is not None:
                with pikepdf.open(orig) as o:
                    for e in edits:
                        recut_in(pdf, o, e["k"], e["left"], e["right"], e["cut_x"])
                    pdf.save(cut)
            else:
                for e in edits:
                    rejoin_in(pdf, e["left"], e["cut_x"], e.get("dy", 0.0))
                pdf.save(cut)
        bilevel = [(e["left"], e["right"]) for e in edits
                   if bilevel_pages(cut, [e["left"], e["right"]])]
        bilevel_idx = [i for pair in bilevel for i in pair]
        clean = tmp / "clean.pdf"
        c.strip_annots(cut, clean)                 # 注釈は最後に移植する
        current = clean
        if orig is not None and bilevel_idx:
            c.despeckle_pdf(clean, tmp / "despeckled.pdf", despeckle_area, pages=bilevel_idx)
            current = tmp / "despeckled.pdf"
        # 同じ言語の予定はまとめて1回の OCR で読む
        groups = {}
        for e in edits:
            groups.setdefault(tuple(e["langs"]), []).append((e["left"], e["right"]))
        for g, (langs, pairs) in enumerate(groups.items(), 1):
            lang = "+".join(langs)
            data = c.choose_tessdata(list(langs))
            spec = page_spec(pairs)
            progress(T(f"読み直しています（{g}/{len(groups)}）：{spec} ページ・{lang}・{data}…",
                       f"Re-reading ({g}/{len(groups)}): pages {spec}, {lang}, {data}…"))
            out = tmp / f"ocr{g}.pdf"
            if orig is not None:
                # 新しく切ったページ（文字がない）だけが読まれ、傾き補正もかかる
                mode = ["--mode", "skip", "--deskew"]
            else:
                mode = ["--mode", "force"]
            c.ocrmypdf(*mode, "--pages", spec, "--output-type", "pdf", "-l", lang,
                       "--jobs", jobs, current, out)
            current = out
        if bilevel_idx:
            bw = tmp / "bw.pdf"
            if binarize_pages(current, bw, bilevel_idx) > 0:
                current = bw
        final = tmp / "final.pdf"
        c.copy_annots(cut, current, final)
        bk = backup(src)
        shutil.move(str(final), str(src))
        c.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as log:
            stamp = f"{datetime.datetime.now():%Y-%m-%d %H:%M}"
            for e in edits:
                origin = f"from {Path(orig).name} p{e['k'] + 1}" if orig is not None else "joined"
                log.write(f"{stamp} RESPLIT {src} | pages {e['left'] + 1}-{e['right'] + 1} | {origin} | "
                          f"cut {e['cut_x']:.1f}pt | {'+'.join(e['langs'])} | backup {bk}\n")
        return bk
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def resplit(src, n, cut_x, langs, jobs="4", progress=print, dy=0.0):
    """1か所だけ切り直す（くっつけて切り直す場合）"""
    return resplit_many(src, [{"left": n, "right": n + 1, "cut_x": cut_x, "langs": langs, "dy": dy}],
                        None, jobs, progress)


def resplit_original(src, orig, k, left, right, cut_x, langs, jobs="4", progress=print):
    """1か所だけ切り直す（元のスキャンから切り直す場合）"""
    return resplit_many(src, [{"k": k, "left": left, "right": right, "cut_x": cut_x, "langs": langs}],
                        Path(orig), jobs, progress)


def render_page(path, index, height_px):
    """1ページを画像にする。戻り値: (PIL画像, ポイント→ピクセルの倍率)"""
    from PIL import Image
    with pikepdf.open(path) as pdf:
        _, wd, hd = sp.display_transform(pdf.pages[index])   # 回転指定を反映した見た目の大きさ
    dpi = max(20, min(150, height_px / (hd / 72)))
    tmp = Path(tempfile.mkdtemp(prefix="eurocr_prev_"))
    try:
        png = tmp / "p.png"
        subprocess.run([c.find_tool("gs"), "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
                        "-sDEVICE=png16m", f"-r{dpi:.1f}", f"-dFirstPage={index + 1}",
                        f"-dLastPage={index + 1}", f"-sOutputFile={png}", str(path)],
                       capture_output=True, timeout=120)
        im = Image.open(png).convert("RGB")
        return im, im.width / wd
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 画面

def run_gui(src):
    import tkinter as tk
    from tkinter import messagebox, filedialog
    from PIL import ImageTk

    src = Path(src).expanduser().resolve()
    with pikepdf.open(src) as pdf:
        npages = len(pdf.pages)

    root = tk.Tk()
    if npages < 2:
        root.withdraw()
        messagebox.showerror("EuroOCR", T("2ページ以上あるPDFが必要です。", "The PDF needs at least two pages."))
        root.destroy()
        return
    root.title(f"EuroOCR-Resplit — {src.name}")
    state = {"orig": None, "map": None, "pair": None, "scale": 1.0, "old_cut": 0.0,
             "cut_px": None, "busy": False, "photo": None, "width_pt": 0.0,
             "dy": 0.0, "auto_dy": 0.0, "parts": None, "ratio": 1.0,
             "queue": {}}     # 切り直しの予定 {左ページの番号(0始まり): 予定}

    top = tk.Frame(root, padx=10, pady=6)
    top.pack(fill="x")
    tk.Label(top, text=T("直したいページ", "Page to fix")).pack(side="left")
    page_var = tk.StringVar(value="1")
    entry = tk.Entry(top, textvariable=page_var, width=6, justify="right")
    entry.pack(side="left", padx=4)
    tk.Label(top, text=f"/ {npages}").pack(side="left")
    btn_show = tk.Button(top, text=T("表示", "Show"))
    btn_prev = tk.Button(top, text=T("◀ 前の見開き", "◀ Prev spread"))
    btn_next = tk.Button(top, text=T("次の見開き ▶", "Next spread ▶"))
    for b in (btn_show, btn_prev, btn_next):
        b.pack(side="left", padx=2)
    btn_orig = tk.Button(top, text=T("元のファイルを選ぶ…", "Choose original…"))
    btn_orig.pack(side="right")
    source_label = tk.Label(root, text="", padx=10, anchor="w", justify="left", fg="#444444")
    source_label.pack(fill="x")

    help_text = T("画像をクリックして切る位置を選びます。赤い線が新しい切れ目、青い点線が今の切れ目です。\n"
                  "← → で前後の見開きへ（引いた切れ目は自動で予定に入ります）。option＋← → で切れ目の微調整"
                  "（shift も押すと大きく）。delete でこの見開きの取り消し。",
                  "Click the image to choose the cut. Red: new cut. Blue dotted: current cut.\n"
                  "← → move to the previous/next spread (the cut you drew is added to the plan automatically). "
                  "option+← → fine-tune the cut (with shift for bigger steps). delete cancels this spread.")
    tk.Label(root, text=help_text, padx=10, anchor="w", justify="left").pack(fill="x")

    canvas = tk.Canvas(root, bg="#888888", highlightthickness=0, cursor="crosshair")
    canvas.pack(padx=10, pady=6)

    langs_frame = tk.Frame(root, padx=10)
    langs_frame.pack(fill="x")
    tk.Label(langs_frame, text=T("読み直す言語:", "Languages:")).pack(side="left")
    lang_vars = {}
    boxes = tk.Frame(langs_frame)
    boxes.pack(side="left")
    for k, code in enumerate(c.LANG_ORDER):
        v = tk.BooleanVar(value=False)
        lang_vars[code] = v
        tk.Checkbutton(boxes, text=f"{c.lang_name(code)} ({code})", variable=v).grid(
            row=k // 4, column=k % 4, sticky="w", padx=4)

    qframe = tk.Frame(root, padx=10, pady=4)
    qframe.pack(fill="x")
    qleft = tk.Frame(qframe)
    qleft.pack(side="left", fill="x", expand=True)
    tk.Label(qleft, text=T("切り直す予定:", "Planned re-splits:"), anchor="w").pack(fill="x")
    qlist = tk.Listbox(qleft, height=4, activestyle="none")
    qlist.pack(fill="x", expand=True)
    qbtns = tk.Frame(qframe)
    qbtns.pack(side="left", padx=8)
    btn_add = tk.Button(qbtns, text=T("予定に加える", "Add to plan"))
    btn_add.pack(fill="x", pady=2)
    btn_undo = tk.Button(qbtns, text=T("この見開きの取り消し（delete）", "Cancel this spread (delete)"))
    btn_undo.pack(fill="x", pady=2)
    btn_del = tk.Button(qbtns, text=T("選んだ予定を外す", "Remove selected"))
    btn_del.pack(fill="x", pady=2)

    bottom = tk.Frame(root, padx=10, pady=8)
    bottom.pack(fill="x")
    status = tk.Label(bottom, text="", anchor="w", fg="#333333", justify="left")
    status.pack(side="left", fill="x", expand=True)
    btn_close = tk.Button(bottom, text=T("閉じる", "Close"))
    btn_close.pack(side="right", padx=4)
    btn_go = tk.Button(bottom, text=T("予定をまとめて切り直す（上書き保存）", "Re-split all planned (overwrite)"))
    btn_go.pack(side="right", padx=4)
    all_buttons = (btn_go, btn_prev, btn_next, btn_show, btn_close, btn_orig, btn_add, btn_del, btn_undo)

    def set_status(text):
        status.config(text=text)

    def set_original(path):
        """元のファイルを使うかどうかを決め、表示を更新する"""
        state["orig"], state["map"] = None, None
        if path:
            m = build_map(path, npages)
            if m is None:
                messagebox.showwarning("EuroOCR", T(
                    f"{Path(path).name} のページの並びが、このファイルと対応しません。"
                    "元のファイルを使わずに切り直します。",
                    f"The pages of {Path(path).name} do not match this file. "
                    "Re-splitting without the original."))
            else:
                state["orig"], state["map"] = Path(path), m
        if state["orig"]:
            source_label.config(text=T(f"元のスキャン: {state['orig'].name}（元の見開きから切り直します）",
                                       f"Original scan: {state['orig'].name} (re-cut from the original spread)"))
        else:
            source_label.config(text=T("元のスキャンが見つかりません。OCR済みの2ページをくっつけて切り直します"
                                       "（行がわずかにずれることがあります）。「元のファイルを選ぶ…」で指定できます。",
                                       "Original scan not found. The two OCRed pages are joined instead (lines may "
                                       "shift slightly). Use “Choose original…” to pick it."))

    def draw_lines():
        canvas.delete("line")
        h = int(canvas.cget("height"))
        old = state["old_cut"] * state["scale"]
        canvas.create_line(old, 0, old, h, fill="#2060ff", dash=(4, 4), width=1, tags="line")
        if state["cut_px"] is not None:
            x = state["cut_px"]
            canvas.create_line(x, 0, x, h, fill="#ff2020", width=2, tags="line")

    def show(page_no=None):
        """page_no（1始まり）のページを含む見開きを表示する。
        その前に、表示中の見開きで引いた切れ目を自動で予定に入れる"""
        if state["busy"]:
            return
        if not commit_current():
            return
        try:
            page_no = int(page_var.get()) if page_no is None else page_no
        except ValueError:
            return
        if not (1 <= page_no <= npages):
            messagebox.showwarning("EuroOCR", T(f"1〜{npages} のページ番号を入れてください。",
                                                f"Enter a page number from 1 to {npages}."))
            return
        n = page_no - 1
        set_status(T("表示しています…", "Loading…"))
        root.update_idletasks()
        height = int(min(root.winfo_screenheight() - 330, 900))
        if state["map"]:
            pair = spread_pair(state["map"], n)
            if pair is None:
                set_status(T(f"{page_no}ページは見開きから分割されたページではありません。",
                             f"Page {page_no} was not split from a spread."))
                return
            k, left, right = pair
            img, scale = render_page(state["orig"], k, height)
            with pikepdf.open(src) as pdf:
                lb = page_box(pdf.pages[left])
            old_cut = lb[2] - lb[0]
            width_pt = img.width / scale
            state["parts"] = None
        else:
            if n >= npages - 1:
                n = npages - 2
            left, right, k = n, n + 1, None
            left_im, right_im, scale, old_cut = render_parts(src, n, height)
            # 左右を別々に傾き補正したときの、つなぎ目の段差を測って合わせる
            state["dy"] = state["auto_dy"] = seam_offset(src, n)
            if n in state["queue"]:
                state["dy"] = state["queue"][n].get("dy", state["dy"])
            state["parts"] = (left_im, right_im, scale, old_cut)
            img = compose(left_im, right_im, scale, old_cut, state["dy"])
            width_pt = img.width / scale
        maxw = root.winfo_screenwidth() - 80
        ratio = min(1.0, maxw / img.width)         # 画面に収まるように縮める
        if ratio < 1.0:
            img = img.resize((int(img.width * ratio), int(img.height * ratio)))
        scale *= ratio
        state.update(pair=(k, left, right), scale=scale, old_cut=old_cut, cut_px=None,
                     width_pt=width_pt, ratio=ratio)
        page_var.set(str(page_no))
        planned = state["queue"].get(left)
        if planned:
            state["cut_px"] = planned["cut_x"] * scale
        put_image(img)
        for v in lang_vars.values():
            v.set(False)
        for code in (planned["langs"] if planned else guess_langs(src, left)):
            lang_vars[code].set(True)
        set_status(page_hint())

    def page_hint():
        k, left, right = state["pair"]
        if left in state["queue"]:
            text = T(f"{left + 1}〜{right + 1}ページ（予定に入っています。クリックし直せば直せます。delete で取り消し）。",
                     f"Pages {left + 1}–{right + 1} (planned; click again to change, delete to cancel).")
        else:
            text = T(f"{left + 1}〜{right + 1}ページ。切り直すなら切る位置をクリックしてください。"
                     "そのまま ← → で移れば、この見開きはそのままです。",
                     f"Pages {left + 1}–{right + 1}. Click where to cut if needed, "
                     "or move on with ← → to leave this spread as it is.")
        if state.get("parts"):
            if abs(state["dy"] - state.get("auto_dy", 0.0)) < 0.01:
                text += T(f"\nつなぎ目の段差を自動で合わせました（右ページを {state['dy']:+.1f} pt）。",
                          f"\nThe step at the seam was matched automatically (right page {state['dy']:+.1f} pt).")
            else:
                text += T(f"\n右ページを {state['dy']:+.1f} pt ずらしています（自動の推定は {state['auto_dy']:+.1f} pt）。",
                          f"\nRight page shifted {state['dy']:+.1f} pt (automatic estimate {state['auto_dy']:+.1f} pt).")
            text += T("はみ出した語の高さが行と合っていなければ、↑ ↓ キーで右ページを上下に動かしてください"
                      "（shift で大きく）。",
                      " If the cut-off words do not line up, move the right page with ↑ ↓ (shift for bigger steps).")
        return text

    def put_image(img):
        state["photo"] = ImageTk.PhotoImage(img)
        canvas.config(width=img.width, height=img.height)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["photo"])
        draw_lines()

    def on_updown(ev):
        """右ページを上下に動かして、つなぎ目の行をそろえる（元のスキャンがないとき）"""
        if state["busy"] or not state.get("parts"):
            return
        step_pt = 2.0 if (ev.state & 0x1) else 0.5
        state["dy"] += step_pt if ev.keysym == "Up" else -step_pt
        left_im, right_im, base_scale, wl = state["parts"]
        img = compose(left_im, right_im, base_scale, wl, state["dy"])
        r = state.get("ratio", 1.0)
        if r < 1.0:
            img = img.resize((int(img.width * r), int(img.height * r)))
        put_image(img)
        set_status(page_hint())

    def step(delta):
        if state["pair"] is None:
            show()
            return
        _, left, right = state["pair"]
        show(max(1, left + 1 - 1) if delta < 0 else min(npages, right + 2))

    def choose_original():
        if state["queue"]:
            if not messagebox.askokcancel("EuroOCR", T(
                    "元のファイルを選び直すと、今の予定は捨てられます。続けますか？",
                    "Choosing another original discards the current plan. Continue?")):
                return
            state["queue"].clear()
            refresh_list()
        state["cut_px"] = None
        path = filedialog.askopenfilename(title=T("元の見開きのPDFを選んでください", "Choose the original spread PDF"),
                                          filetypes=[("PDF", "*.pdf")], initialdir=str(src.parent))
        if path:
            set_original(Path(path))
            show()

    def on_click(ev):
        if state["busy"] or state["pair"] is None:
            return
        state["cut_px"] = max(1, min(int(canvas.cget("width")) - 1, ev.x))
        draw_lines()
        canvas.focus_set()
        set_status(T("切れ目を選びました。ほかの見開きへ移ると自動で予定に入ります（delete で取り消し）。",
                     "Cut chosen. It is added to the plan when you move to another spread (delete cancels)."))

    def typing():
        """ページ番号の欄などに入力中なら True（矢印キーは文字の移動に使う）"""
        return isinstance(root.focus_get(), (tk.Entry, tk.Listbox))

    def fine_tune(ev, step_px):
        if typing() or state["cut_px"] is None or state["busy"]:
            return "break"
        state["cut_px"] += -step_px if ev.keysym == "Left" else step_px
        draw_lines()
        return "break"

    def on_arrow(ev):
        """← → で前後の見開きへ移る"""
        if typing() or state["busy"]:
            return
        step(-1 if ev.keysym == "Left" else +1)
        return "break"

    def commit_current():
        """表示中の見開きで引いた切れ目（と言語）を、予定に入れる。入れられなければ False"""
        if state["pair"] is None or state["cut_px"] is None:
            return True
        left = state["pair"][1]
        langs = [code for code, v in lang_vars.items() if v.get()]
        e = state["queue"].get(left)
        if (e and abs(e["cut_x"] - state["cut_px"] / state["scale"]) < 0.01 and e["langs"] == langs
                and abs(e.get("dy", 0.0) - state.get("dy", 0.0)) < 0.01):
            return True
        return add_current(quiet=True) is True

    def undo_current(_ev=None):
        """表示中の見開きの予定と赤い線を取り消す"""
        if state["busy"] or state["pair"] is None:
            return
        if _ev is not None and typing():
            return
        left = state["pair"][1]
        state["queue"].pop(left, None)
        state["cut_px"] = None
        draw_lines()
        refresh_list()
        set_status(T("この見開きの切り直しを取り消しました。", "The re-split of this spread was cancelled."))
        return "break"

    def refresh_list():
        qlist.delete(0, "end")
        for left in sorted(state["queue"]):
            e = state["queue"][left]
            qlist.insert("end", T(
                f"{e['left'] + 1}〜{e['right'] + 1}ページ：切れ目 {e['cut_x']:.0f} pt（今 {e['old_cut']:.0f} pt）・"
                f"{'+'.join(e['langs'])}",
                f"pages {e['left'] + 1}–{e['right'] + 1}: cut {e['cut_x']:.0f} pt (now {e['old_cut']:.0f} pt), "
                f"{'+'.join(e['langs'])}"))
        btn_go.config(text=T(f"予定をまとめて切り直す（{len(state['queue'])}か所・上書き保存）",
                             f"Re-split all planned ({len(state['queue'])}, overwrite)"))

    def add_current(quiet=False, from_go=False):
        """表示中の見開きの切る位置と言語を、予定に加える（すでにあれば直す）。
        戻り値: True＝加えた、False＝加えられない、None＝ほかの予定と重なるので加えなかった（from_go のとき）"""
        if state["busy"] or state["pair"] is None:
            return False
        if state["cut_px"] is None:
            if not quiet:
                messagebox.showinfo("EuroOCR", T("先に画像をクリックして切る位置を選んでください。",
                                                 "Click the image first to choose the cut."))
            return False
        langs = [code for code, v in lang_vars.items() if v.get()]
        if not langs:
            messagebox.showinfo("EuroOCR", T("言語を一つ以上選んでください。", "Choose at least one language."))
            return False
        k, left, right = state["pair"]
        if state["orig"] is None:
            # くっつけて切り直す場合、隣り合う2つの予定が同じページを含まないようにする
            clash = [l for l in state["queue"] if l != left and abs(l - left) <= 1]
            if clash and from_go:
                return None
            if clash:
                messagebox.showwarning("EuroOCR", T(
                    f"{clash[0] + 1}〜{clash[0] + 2}ページの予定と重なります。どちらかを外してください。",
                    f"This overlaps the plan for pages {clash[0] + 1}–{clash[0] + 2}. Remove one of them."))
                return False
        state["queue"][left] = {"k": k, "left": left, "right": right,
                                "cut_x": state["cut_px"] / state["scale"], "langs": langs,
                                "dy": state.get("dy", 0.0), "old_cut": state["old_cut"]}
        refresh_list()
        set_status(page_hint())
        return True

    def remove_selected():
        if state["busy"]:
            return
        keys = sorted(state["queue"])
        for i in reversed(qlist.curselection()):
            state["queue"].pop(keys[i], None)
        refresh_list()

    def on_select(_ev=None):
        """一覧で選んだ予定の見開きを表示する"""
        sel = qlist.curselection()
        if sel and not state["busy"]:
            show(sorted(state["queue"])[sel[0]] + 1)

    def go():
        if state["busy"]:
            return
        # 表示中の見開きで線を引いたまま予定に加えていなければ、加える
        if state["pair"] is not None and state["cut_px"] is not None:
            left = state["pair"][1]
            e = state["queue"].get(left)
            if e is None or abs(e["cut_x"] - state["cut_px"] / state["scale"]) > 0.01:
                added = add_current(quiet=True, from_go=True)
                if added is False:
                    return
                if added is None:
                    state["cut_px"] = None       # 重なる線は予定に入れず、すでにある予定だけを行う
                    draw_lines()
        if not state["queue"]:
            messagebox.showinfo("EuroOCR", T("切り直す予定がありません。切る位置をクリックして「予定に加える」を押してください。",
                                             "Nothing is planned. Click a cut and press “Add to plan”."))
            return
        n_plans = len(state["queue"])
        if not messagebox.askokcancel("EuroOCR", T(
                f"{n_plans}か所を切り直して、このファイルを上書き保存します。ほかのアプリで開いていて保存していない"
                "変更（付箋など）があれば、先に保存してください。\n\n上書き前の版は ~/EuroOCR/backup に残ります。続けますか？",
                f"{n_plans} spread(s) will be re-split and the file overwritten. If it is open in another app with "
                "unsaved changes (notes etc.), save them first.\n\nThe previous version is kept in ~/EuroOCR/backup. "
                "Continue?")):
            return
        edits = [dict(e) for e in state["queue"].values()]
        orig = state["orig"]
        current_left = state["pair"][1] if state["pair"] else 0
        state["busy"] = True
        for b in all_buttons:
            b.config(state="disabled")
        result = {}
        messages = queue.Queue()     # 作業中の知らせは、画面側が取りに行く（Tk は別スレッドから触らない）

        def work():
            try:
                result["backup"] = resplit_many(src, edits, orig, progress=messages.put)
            except Exception as e:
                result["error"] = e

        def poll():
            while not messages.empty():
                set_status(messages.get())
            if th.is_alive():
                root.after(300, poll)
                return
            state["busy"] = False
            for b in all_buttons:
                b.config(state="normal")
            if "error" in result:
                set_status(T("失敗しました。予定はそのまま残っています。", "Failed. The plan is kept."))
                messagebox.showerror("EuroOCR", str(result["error"]))
            else:
                state["queue"].clear()
                state["cut_px"] = None
                refresh_list()
                show(current_left + 1)
                set_status(T(f"完了しました（{n_plans}か所）。続けて別のページも直せます。",
                             f"Done ({n_plans} spread(s)). You can fix more pages."))
                c.notify(T(f"切り直しが完了しました（{n_plans}か所）", f"Re-split complete ({n_plans})"))

        th = threading.Thread(target=work, daemon=True)
        th.start()
        root.after(300, poll)

    def close():
        if state["busy"]:
            return
        if state["queue"] and not messagebox.askokcancel("EuroOCR", T(
                f"まだ切り直していない予定が{len(state['queue'])}か所あります。予定を捨てて閉じますか？",
                f"{len(state['queue'])} planned re-split(s) have not been done. Discard them and close?")):
            return
        root.destroy()

    btn_show.config(command=lambda: show())
    btn_prev.config(command=lambda: step(-1))
    btn_next.config(command=lambda: step(+1))
    btn_orig.config(command=choose_original)
    btn_go.config(command=go)
    btn_add.config(command=add_current)
    btn_del.config(command=remove_selected)
    btn_close.config(command=close)
    root.protocol("WM_DELETE_WINDOW", close)
    qlist.bind("<Double-Button-1>", on_select)
    entry.bind("<Return>", lambda e: show())
    canvas.bind("<Button-1>", on_click)
    btn_undo.config(command=undo_current)
    root.bind_all("<Left>", on_arrow)
    root.bind_all("<Right>", on_arrow)
    # 微調整：Mac では option、ほかの環境では alt
    for mod in ("Option", "Alt"):
        try:
            root.bind_all(f"<{mod}-Left>", lambda e: fine_tune(e, 1))
            root.bind_all(f"<{mod}-Right>", lambda e: fine_tune(e, 1))
            root.bind_all(f"<Shift-{mod}-Left>", lambda e: fine_tune(e, 5))
            root.bind_all(f"<Shift-{mod}-Right>", lambda e: fine_tune(e, 5))
        except tk.TclError:
            pass
    for key in ("<Up>", "<Down>", "<Shift-Up>", "<Shift-Down>"):
        root.bind_all(key, lambda e: None if typing() else on_updown(e))
    for key in ("<Delete>", "<BackSpace>"):
        root.bind_all(key, undo_current)

    def show_first():
        """最初に切り直せる見開きを表示する"""
        if state["map"]:
            for p in range(npages):
                if spread_pair(state["map"], p):
                    show(p + 1)
                    return
        show(1)

    set_original(find_original(src))
    refresh_list()
    root.after(100, show_first)
    root.lift()
    root.attributes("-topmost", True)
    root.after(800, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.mainloop()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    run_gui(sys.argv[1])


if __name__ == "__main__":
    main()

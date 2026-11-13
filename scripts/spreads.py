# Copyright (c) 2026 Masahiro Kitano (北野雅弘)
# SPDX-License-Identifier: MIT
"""
EuroOCR: 見開きの分割と、白紙の1ページ目の判定 / Splitting two-page spreads
画像は切らずに各ページの表示範囲を半分にする（画質の劣化なし）。
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pikepdf
from pikepdf import Name, Array

from common import T, find_tool

WIDE_RATIO = 1.15


def box_of(page):
    """ページの見える範囲（CropBox があればそれ、なければ MediaBox）"""
    box = page.obj.get(Name.CropBox, page.obj.MediaBox)
    x0, y0, x1, y1 = (float(v) for v in box)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def is_spread(page):
    x0, y0, x1, y1 = box_of(page)
    rot = int(page.obj.get(Name.Rotate, 0)) % 360
    w, h = x1 - x0, y1 - y0
    if rot in (90, 270):
        w, h = h, w
    return w >= h * WIDE_RATIO


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def display_transform(page):
    """ページの座標を「見た目どおりの向き」の座標（左下が原点）に移す変換と、見た目の幅・高さ。
    回転指定（/Rotate、時計回り）を反映する。戻り値: ((a, b, c, d, e, f), 幅, 高さ)
    変換は X = a*x + c*y + e, Y = b*x + d*y + f"""
    x0, y0, x1, y1 = box_of(page)
    w, h = x1 - x0, y1 - y0
    rot = int(page.obj.get(Name.Rotate, 0)) % 360
    if rot == 90:
        return (0.0, -1.0, 1.0, 0.0, -y0, w + x0), h, w
    if rot == 180:
        return (-1.0, 0.0, 0.0, -1.0, x0 + w, y0 + h), w, h
    if rot == 270:
        return (0.0, 1.0, -1.0, 0.0, y0 + h, -x0), h, w
    return (1.0, 0.0, 0.0, 1.0, -x0, -y0), w, h


def apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def make_half(dst, page, x_from, x_to):
    """page を複製し、見た目どおりの向きで横方向 x_from〜x_to（ポイント）の範囲だけを
    表示するページにする。回転指定は内容の向きに組み込んで取り除き、座標の原点を (0,0)
    に合わせ直す（OCRソフトや切り直しで位置がずれないように）。内容そのものは書き換えない"""
    m, _, hd = display_transform(page)
    dst.pages.append(page)
    new = dst.pages[-1]
    # 同じページを2回複製すると内容の指定が共有されることがあるので、
    # 元ページの内容から組み立て直す
    orig = page.obj.get(Name.Contents)
    if orig is None:
        parts = []
    elif isinstance(orig, Array):
        parts = [dst.copy_foreign(s) for s in orig]
    else:
        parts = [dst.copy_foreign(orig)]
    a, b, c, d, e, f = m
    cm = dst.make_indirect(pikepdf.Stream(
        dst, f"{a:g} {b:g} {c:g} {d:g} {e - x_from:.4f} {f:.4f} cm\n".encode()))
    new.obj.Contents = Array([cm, *parts])
    new.obj.MediaBox = Array([0, 0, x_to - x_from, hd])
    for key in (Name.CropBox, Name.BleedBox, Name.TrimBox, Name.ArtBox, Name.Rotate):
        if key in new.obj:
            del new.obj[key]
    return new


def split_annots(halves, dst, m=IDENTITY):
    """複製したページの注釈を、見た目の横位置で左右のページに振り分けて座標を直す。
    halves: [{"page", "x_from", "x_to"}, ...]（見た目どおりの向きの座標）
    m: 元のページの座標を見た目の座標に移す変換（display_transform の値）。
    回転のないときは外観（AP）をそのまま使い、回転を取り除いたときは外観を外して
    表示するアプリに描き直させる"""
    rotated = (m[1], m[2]) != (0.0, 0.0) or m[0] < 0
    orig = []
    for h in halves:
        if Name.Annots in h["page"].obj:
            if not orig:
                orig = list(h["page"].obj.Annots)
            del h["page"].obj[Name.Annots]
    n = 0
    for a in orig:
        if Name.Rect not in a or a.get(Name.Subtype) == Name.Popup:
            continue
        r = [float(v) for v in a.Rect]
        corners = [apply(m, x, y) for x, y in ((r[0], r[1]), (r[2], r[3]))]
        cx = (corners[0][0] + corners[1][0]) / 2
        target = next((h for h in halves if h["x_from"] <= cx < h["x_to"]), halves[-1])
        na = dst.make_indirect(pikepdf.Dictionary(a))
        dx = target["x_from"]

        def move(arr):
            vals = [float(v) for v in arr]
            out = []
            for i in range(0, len(vals) - 1, 2):
                X, Y = apply(m, vals[i], vals[i + 1])
                out += [X - dx, Y]
            return Array(out)

        xs = [cx_ - dx for cx_, _ in corners]
        ys = [cy_ for _, cy_ in corners]
        na.Rect = Array([min(xs), min(ys), max(xs), max(ys)])
        for key in (Name.QuadPoints, Name.Vertices, Name.L):
            if key in na:
                na[key] = move(na[key])
        if Name.InkList in na:
            na.InkList = Array([move(s) for s in na.InkList])
        for key in (Name.Popup, Name.P):
            if key in na:
                del na[key]
        if rotated and Name.AP in na:
            del na[Name.AP]
        na.P = target["page"].obj
        if Name.Annots not in target["page"].obj:
            target["page"].obj.Annots = Array()
        target["page"].obj.Annots.append(na)
        n += 1
    return n


GUTTER_SEARCH = 0.10   # 中央から左右にこの割合（見開き全体の幅に対して）まで余白を探す
GUTTER_DPI = 150
CUT_MIN = 3     # 真ん中の線を横切る単語がこれ以上あれば「文字を切る」とみなす
FREE_MAX = 1    # 横切るものがこれ以下の列は「余白」とみなす（迷い込んだ線などを許す）


def letter_boxes(arr):
    """ページ画像から、単語ぐらいの大きさの黒いかたまりの位置（x0, x1）を返す。
    縦に長い線（ノドの影など）、点状のゴミ、大きな図版は除く"""
    import cv2
    import numpy as np
    h, w = arr.shape
    _, black = cv2.threshold(arr, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    black = black.astype(np.uint8)
    # 点状のゴミを先に消す（つないだときに文字とくっつかないように）
    n0, lab0, st0, _ = cv2.connectedComponentsWithStats(black, connectivity=8)
    black[np.isin(lab0, np.where(st0[:, cv2.CC_STAT_AREA] < 4)[0][1:])] = 0
    # 横に少しだけ太らせて、同じ単語の文字どうしをつなぐ（文字と文字の間で切っても
    # 「単語を切った」とわかるように）
    k = max(3, round(GUTTER_DPI / 40))
    joined = cv2.dilate(black, np.ones((1, k), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    boxes = []
    for x, y, bw, bh, area in stats[1:]:
        if not (h * 0.003 <= bh <= h * 0.08):     # 文字の高さに合わないもの（縦線・図版・罫線）
            continue
        if bw > w * 0.6:                          # 見開きの大半にわたるもの
            continue
        if not (h * 0.04 <= y + bh / 2 <= h * 0.96):   # 上下の端（スキャナーの影など）
            continue
        boxes.append((x, x + bw))
    return boxes


def crossing_counts(boxes, w):
    """各列 x について、x を横切る（x0 < x < x1-1）文字の数"""
    import numpy as np
    diff = np.zeros(w + 1, dtype=int)
    for x0, x1 in boxes:
        if x1 - x0 >= 3:
            diff[x0 + 1] += 1
            diff[x1 - 1] -= 1
    return np.cumsum(diff)[:w]


def find_gutters(src, page_indexes):
    """見開きのページごとに、切る位置（左端からの割合）を決める。
    真ん中で切ると文字を横切る（3文字以上）ときだけ、文字を横切らない位置のうち
    真ん中にいちばん近い余白の真ん中にずらす。それ以外は 0.5（真ん中）。
    戻り値: {ページ番号(0始まり): 割合}"""
    import numpy as np
    from PIL import Image
    result = {}
    if not page_indexes:
        return result
    tmp = Path(tempfile.mkdtemp(prefix="eurocr_gutter_"))
    try:
        subprocess.run([find_tool("gs"), "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
                        "-sDEVICE=pnggray", f"-r{GUTTER_DPI}",
                        f"-sOutputFile={tmp}/p%05d.png", str(src)],
                       capture_output=True, timeout=1800)
        for i in page_indexes:
            png = tmp / f"p{i + 1:05d}.png"
            if not png.exists():
                continue
            arr = np.array(Image.open(png).convert("L"))
            h, w = arr.shape
            cross = crossing_counts(letter_boxes(arr), w)
            c = w // 2
            if cross[max(0, c - 1):c + 2].min() < CUT_MIN:
                result[i] = 0.5                       # 真ん中で切っても文字を切らない
                continue
            lo, hi = int(w * (0.5 - GUTTER_SEARCH)), int(w * (0.5 + GUTTER_SEARCH))
            # 文字を横切らない列が続く「余白の帯」を集める（探す範囲の外まで続く帯は端までたどる）
            bands, x = [], lo
            while x <= hi:
                if cross[x] <= FREE_MAX:
                    a = x
                    while a - 1 >= int(w * 0.25) and cross[a - 1] <= FREE_MAX:
                        a -= 1
                    b = x
                    while b + 1 <= int(w * 0.75) and cross[b + 1] <= FREE_MAX:
                        b += 1
                    bands.append((a, b))
                    x = b + 1
                else:
                    x += 1
            # 文字の間の偶然の隙間を除くため、ある程度の幅がある帯だけを候補にする
            bands = [(a, b) for a, b in bands if b - a + 1 >= max(3, w * 0.006)]
            if not bands:
                result[i] = 0.5                       # 文字を避けられる位置がない → 真ん中
                continue
            a, b = min(bands, key=lambda ab: min(abs(ab[0] - c), abs(ab[1] - c)))
            result[i] = ((a + b) / 2 + 0.5) / w
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return result


def split_pdf(src, dst_path, rtl, gutter, keep_first, keep_last, auto_gutter=False):
    with pikepdf.open(src) as pdf:
        out = pikepdf.new()
        n = len(pdf.pages)
        split_count = 0
        notes = []
        gutters = {}
        if auto_gutter:
            targets = [i for i, p in enumerate(pdf.pages)
                       if not (i < keep_first or i >= n - keep_last) and is_spread(p)
                       and int(p.obj.get(Name.Rotate, 0)) % 360 == 0]
            gutters = find_gutters(src, targets)
            moved = sorted(i + 1 for i, g in gutters.items() if abs(g - 0.5) > 0.002)
            if moved:
                shown = ", ".join(map(str, moved[:10])) + (" …" if len(moved) > 10 else "")
                notes.append(T(f"ノドの位置を補正: {len(moved)}見開き（{shown}）",
                               f"gutter adjusted on {len(moved)} spread(s) ({shown})"))
        for i, page in enumerate(pdf.pages):
            keep = i < keep_first or i >= n - keep_last
            if keep or not is_spread(page):
                out.pages.append(page)
                continue
            m, wd, _ = display_transform(page)
            mid = wd * gutters.get(i, gutter)
            parts = [(0.0, mid), (mid, wd)]
            if rtl:
                parts.reverse()
            halves = []
            for xf, xt in parts:
                np_ = make_half(out, page, xf, xt)
                halves.append({"page": np_, "x_from": xf, "x_to": xt})
            split_annots(sorted(halves, key=lambda h: h["x_from"]), out, m)
            split_count += 1
        if split_count:
            out.save(dst_path)
        return n, split_count, len(out.pages), notes



def render_first_page(pdf_path, png_path, dpi=75):
    """1ページ目をグレーの画像にする（Ghostscript）"""
    gs = find_tool("gs")
    subprocess.run([gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pnggray",
                    f"-r{dpi}", "-dFirstPage=1", "-dLastPage=1",
                    f"-sOutputFile={png_path}", str(pdf_path)],
                   capture_output=True, timeout=120)


def ink_ratio(pdf_path):
    """1ページ目のインクの量（%）。周囲10%を除き、点状のゴミを消し、
    地の色より 80 以上暗い点だけを数える（薄い裏写りは数えない）"""
    from PIL import Image, ImageFilter
    tmp = Path(tempfile.mkdtemp(prefix="eurocr_blank_"))
    try:
        png = tmp / "p1.png"
        render_first_page(pdf_path, png)
        if not png.exists():
            raise RuntimeError(T("1ページ目を画像にできませんでした", "could not render page 1"))
        im = Image.open(png).convert("L")
        w, h = im.size
        im = im.crop((int(w * 0.10), int(h * 0.10), int(w * 0.90), int(h * 0.90)))
        im = im.filter(ImageFilter.MedianFilter(3))
        hist = im.histogram()
        paper = max(range(256), key=lambda v: hist[v])
        return sum(hist[:max(0, paper - 80)]) / sum(hist) * 100
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def drop_blank_first(path, threshold=0.02):
    """path の1ページ目が白紙なら削除する。戻り値: (削除したか, インク量%)"""
    ratio = ink_ratio(path)
    if ratio >= threshold:
        return False, ratio
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        if len(pdf.pages) <= 1:
            return False, ratio
        if Name.Annots in pdf.pages[0].obj and len(pdf.pages[0].obj.Annots):
            return False, ratio
        del pdf.pages[0]
        pdf.save(path)
    return True, ratio

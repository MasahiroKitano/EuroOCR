# Copyright (c) 2026 Masahiro Kitano (北野雅弘)
# SPDX-License-Identifier: MIT
"""
EuroOCR 共通部品 / shared parts
  表示言語、外部ツールの場所、PDFの種類の判定、言語判定、OCRの呼び出し、注釈の移植、
  ノイズ除去。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zlib
from pathlib import Path

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pikepdf
from pikepdf import Name, Array, PdfImage

HOME_DIR = Path.home() / "EuroOCR"
BEST_DIR = HOME_DIR / "tessdata_best"     # 本番のOCRに使う精度優先のデータ
FAST_DIR = HOME_DIR / "tessdata_fast"     # 言語判定の試し読みに使う速いデータ
LOG_DIR = HOME_DIR / "logs"

LANG_ORDER = ["eng", "deu", "fra", "ita", "spa", "lat", "grc"]


# ---------------------------------------------------------------- 表示言語

def _detect_ui():
    v = os.environ.get("EUROOCR_UI")
    if v in ("ja", "en"):
        return v
    try:
        r = subprocess.run(["defaults", "read", "-g", "AppleLanguages"],
                           capture_output=True, text=True, timeout=5)
        first = re.findall(r'"?([A-Za-z-]+)"?', r.stdout.replace("(", " "))
        return "ja" if first and first[0].lower().startswith("ja") else "en"
    except Exception:
        return "en"


UI = _detect_ui()


def T(ja, en):
    """表示言語に合わせて日本語か英語を返す"""
    return ja if UI == "ja" else en


LANG_NAME = {
    "eng": ("英語", "English"), "deu": ("ドイツ語", "German"),
    "fra": ("フランス語", "French"), "ita": ("イタリア語", "Italian"),
    "spa": ("スペイン語", "Spanish"), "lat": ("ラテン語", "Latin"),
    "grc": ("古典ギリシャ語", "Ancient Greek"),
}


def lang_name(code):
    ja, en = LANG_NAME[code]
    return T(ja, en)


# ---------------------------------------------------------------- 外部ツール

def brew_prefix():
    for p in ("/opt/homebrew", "/usr/local"):
        if Path(p, "bin", "brew").exists():
            return Path(p)
    return Path("/opt/homebrew")


def find_tool(name):
    return shutil.which(name) or str(brew_prefix() / "bin" / name)


# Homebrew の場所を PATH に加える（OCRmyPDF が tesseract や gs を見つけられるように）
_brew_bin = str(brew_prefix() / "bin")
if _brew_bin not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _brew_bin + os.pathsep + os.environ.get("PATH", "")


def tess_configs_dir():
    """Tesseract 付属の設定ファイル（configs, tessconfigs）のある場所"""
    for p in (brew_prefix() / "share" / "tessdata", Path("/usr/share/tesseract-ocr/5/tessdata")):
        if (p / "configs").exists():
            return p
    return brew_prefix() / "share" / "tessdata"


def ensure_configs(data_dir):
    """認識データのフォルダに configs / tessconfigs へのリンクを用意する"""
    std = tess_configs_dir()
    for sub in ("configs", "tessconfigs"):
        link = data_dir / sub
        if not link.exists() and (std / sub).exists():
            try:
                link.symlink_to(std / sub)
            except OSError:
                pass


def choose_tessdata(langs):
    """選んだ言語が全部 best版にあれば best版、なければ通常版（試し読み用の速いデータ）。
    環境変数 TESSDATA_PREFIX を設定し、表示用の説明を返す"""
    missing = [l for l in list(langs) + ["osd"] if not (BEST_DIR / f"{l}.traineddata").exists()]
    if not missing:
        ensure_configs(BEST_DIR)
        os.environ["TESSDATA_PREFIX"] = str(BEST_DIR)
        return T("best版", "best")
    if all((FAST_DIR / f"{l}.traineddata").exists() for l in langs):
        ensure_configs(FAST_DIR)
        os.environ["TESSDATA_PREFIX"] = str(FAST_DIR)
    else:
        os.environ.pop("TESSDATA_PREFIX", None)
    return T(f"通常版（best版に {', '.join(missing)} がない）",
             f"standard (best data missing: {', '.join(missing)})")


# ---------------------------------------------------------------- PDFの種類

CATEGORY = {
    "redo": ("検索可能な画像 → 文字の層だけ入れ替え", "searchable image → replace text layer"),
    "clearscan": ("ClearScan → 作り直し", "ClearScan → rebuild"),
    "scan": ("文字層なし → ノイズ除去・傾き補正・OCR", "no text layer → clean, deskew, OCR"),
    "digital": ("電子版（元から文字） → 処理不要", "born-digital → nothing to do"),
    "japanese": ("日本語中心 → 処理しない", "mainly Japanese → skipped"),
    "forced": ("強制OCR → 全ページ作り直し", "forced OCR → rebuild all pages"),
    "scanocr": ("文字入りスキャン（コピー機・スキャナーのOCR） → ノイズ除去・傾き補正・作り直し",
                "scan with copier/scanner OCR text → clean, deskew, rebuild"),
    "finereader": ("FineReaderでOCR済み・ギリシャ語あり → 作り直し",
                   "FineReader OCR with Greek → rebuild"),
    "monotonic": ("ギリシャ語が現代ギリシャ語として認識済み → 作り直し",
                  "Greek read as modern Greek → rebuild"),
}


def category_name(cat):
    ja, en = CATEGORY[cat]
    return T(ja, en)


def page_images(page):
    try:
        return list(page.get_images().values())
    except AttributeError:
        return list(page.images.values())


def count_text(obj, resources, tr, depth, counts):
    """内容ストリームを読み、見える文字と透明な文字の命令を数える（フォーム内も）"""
    if depth > 6:
        return
    try:
        ops = pikepdf.parse_content_stream(obj)
    except Exception:
        return
    stack = []
    for operands, op in ops:
        o = str(op)
        if o == "q":
            stack.append(tr)
        elif o == "Q":
            tr = stack.pop() if stack else 0
        elif o == "Tr" and operands:
            try:
                tr = int(operands[0])
            except Exception:
                pass
        elif o in ("Tj", "TJ", "'", '"'):
            counts["invisible" if tr == 3 else "visible"] += 1
        elif o == "Do" and operands and resources is not None:
            try:
                xobj = resources.XObject[operands[0]]
            except Exception:
                continue
            if xobj.get(Name.Subtype) == Name.Form:
                count_text(xobj, xobj.get(Name.Resources, resources), tr, depth + 1, counts)


def _matmul(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2,
            e * a2 + f * c2 + e2, e * b2 + f * d2 + f2)


def image_coverage(page):
    """ページに描かれた画像のうち、いちばん大きいものがページの何割を覆うか（0〜1）"""
    x0, y0, x1, y1 = (float(v) for v in page.obj.get(Name.CropBox, page.obj.MediaBox))
    page_area = abs((x1 - x0) * (y1 - y0)) or 1.0
    best = 0.0

    def walk(obj, resources, ctm, depth):
        nonlocal best
        if depth > 4:
            return
        try:
            ops = pikepdf.parse_content_stream(obj)
        except Exception:
            return
        stack = []
        for operands, op in ops:
            o = str(op)
            if o == "q":
                stack.append(ctm)
            elif o == "Q":
                ctm = stack.pop() if stack else ctm
            elif o == "cm" and len(operands) == 6:
                try:
                    ctm = _matmul(tuple(float(v) for v in operands), ctm)
                except Exception:
                    pass
            elif o == "Do" and operands and resources is not None:
                try:
                    xobj = resources.XObject[operands[0]]
                except Exception:
                    continue
                sub = xobj.get(Name.Subtype)
                if sub == Name.Image:
                    best = max(best, abs(ctm[0] * ctm[3] - ctm[1] * ctm[2]) / page_area)
                elif sub == Name.Form:
                    fm = tuple(float(v) for v in xobj.get(Name.Matrix, [1, 0, 0, 1, 0, 0]))
                    walk(xobj, xobj.get(Name.Resources, resources), _matmul(fm, ctm), depth + 1)

    walk(page.obj, page.obj.get(Name.Resources), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), 0)
    return min(best, 1.0)


def classify(pdf, sample_pages=24):
    n = len(pdf.pages)
    bits = set()
    pages_with_bilevel = 0
    has_images = False
    for page in pdf.pages:
        page_has_bilevel = False
        for img in page_images(page):
            has_images = True
            b = 1 if img.get(Name.ImageMask, False) else int(img.get(Name.BitsPerComponent, 8))
            bits.add(b)
            if b == 1:
                page_has_bilevel = True
        if page_has_bilevel:
            pages_with_bilevel += 1
    if n <= sample_pages:
        idx = list(range(n))
    else:
        idx = sorted({int(i * (n - 1) / (sample_pages - 1)) for i in range(sample_pages)})
    counts = {"visible": 0, "invisible": 0}
    full_image_pages = 0
    text_pages = 0
    for i in idx:
        page = pdf.pages[i]
        before = counts["visible"] + counts["invisible"]
        count_text(page.obj, page.obj.get(Name.Resources), 0, 0, counts)
        if counts["visible"] + counts["invisible"] > before:
            text_pages += 1
        if image_coverage(page) >= 0.85:
            full_image_pages += 1
    # ほぼ全ページが「ページ全体を覆う画像」でできている＝スキャン
    scan_like = full_image_pages >= len(idx) * 0.8
    visible, invisible = counts["visible"], counts["invisible"]
    total = visible + invisible
    if total == 0 or text_pages < len(idx) * 0.3:
        # 文字のあるページがごく一部（表紙だけ Acrobat で OCR した、など）→ スキャンの本。
        # 文字のあるページはそのまま残し、文字のないページだけを読み取る
        cat = "scan"
    elif visible > total * 0.2:
        if pages_with_bilevel >= n * 0.5 and not scan_like:
            cat = "clearscan"
        elif scan_like:
            # 見える文字があっても、ページ全体の画像の下に敷かれた OCR の文字
            # （コピー機・スキャナー・Acrobat の文字入りスキャン）
            cat = "scanocr"
        else:
            cat = "digital"
    else:
        cat = "redo"
    producer = str(pdf.docinfo.get("/Producer", "")) if pdf.docinfo else ""
    creator = str(pdf.docinfo.get("/Creator", "")) if pdf.docinfo else ""
    return {"cat": cat, "all_bilevel": has_images and bits <= {1}, "has_images": has_images,
            "any_bilevel": 1 in bits, "producer": producer, "creator": creator}


def extract_text(path, npages, first=None, span=20):
    """文字層の文字を取り出す（Ghostscript）"""
    if first is None:
        first = 1 if span >= npages else (3 if npages >= 6 else 1)
    last = min(npages, first + span - 1)
    cmd = [find_tool("gs"), "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=txtwrite",
           f"-dFirstPage={first}", f"-dLastPage={last}", "-sOutputFile=-", str(path)]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=1800).stdout.decode(
            "utf-8", errors="ignore")
    except Exception:
        return ""


def greek_letters(text):
    text = unicodedata.normalize("NFC", text)
    total = sum(1 for ch in text if "Ͱ" <= ch <= "Ͽ" or "ἀ" <= ch <= "῿")
    poly = sum(1 for ch in text if "ἀ" <= ch <= "῿")
    return total, poly


def refine_digital(info, path, npages):
    """「電子版」を、OCRソフトで作られたものかどうかでさらに分ける"""
    meta = (info["producer"] + " " + info["creator"]).lower()
    total, poly = greek_letters(extract_text(path, npages, first=1, span=npages))
    if "paper capture" in meta:
        return "clearscan"
    if total >= 20 and ("finereader" in meta or "abbyy" in meta):
        return "finereader"
    if total >= 50 and poly <= total * 0.02:
        return "monotonic"
    return "digital"


def ocr_sample(path, npages, lang, fractions, data_dir=FAST_DIR):
    """数ページだけ画像にして Tesseract で試し読みした文字列を返す"""
    tess = find_tool("tesseract")
    if npages <= len(fractions):
        pages = list(range(1, npages + 1))
    else:
        pages = [max(1, int(npages * f)) for f in fractions]
    text = ""
    tmp = Path(tempfile.mkdtemp(prefix="eurocr_sample_"))
    try:
        for p in pages:
            png = tmp / f"p{p}.png"
            subprocess.run([find_tool("gs"), "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
                            "-sDEVICE=pnggray", "-r200", f"-dFirstPage={p}", f"-dLastPage={p}",
                            f"-sOutputFile={png}", str(path)], capture_output=True, timeout=120)
            if not png.exists():
                continue
            cmd = [tess, str(png), "stdout", "-l", lang]
            if data_dir and Path(data_dir).exists():
                cmd[1:1] = ["--tessdata-dir", str(data_dir)]
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            text += r.stdout.decode("utf-8", errors="ignore") + "\n"
    except Exception:
        pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return text


def is_japanese(text):
    jp = sum(1 for ch in text if "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿")
    latin = sum(1 for ch in text if ("a" <= ch <= "z") or ("A" <= ch <= "Z"))
    return jp >= 150 and jp > latin * 0.5


def japanese_check(cat, path, npages):
    if cat == "scan":
        if not (FAST_DIR / "jpn.traineddata").exists():
            return False
        return is_japanese(ocr_sample(path, npages, "jpn", (0.4, 0.6)))
    return is_japanese(extract_text(path, npages))


def decide(src):
    """戻り値: (種類, 情報, ページ数)"""
    with pikepdf.open(src) as pdf:
        npages = len(pdf.pages)
        info = classify(pdf)
    cat = info["cat"]
    if japanese_check(cat, src, npages):
        return "japanese", info, npages
    if cat == "digital":
        cat = refine_digital(info, src, npages)
    return cat, info, npages


# ---------------------------------------------------------------- 言語判定

STOPWORDS = {
    "eng": set("the and of to is that which with this are was for not".split()),
    "deu": set("der die und das ist nicht mit den zu sich des ein eine auch".split()),
    "fra": set("le les et des est que une dans du pas qui sur au".split()),
    "ita": set("il che di del della non per sono gli nel una anche".split()),
    # 他の言語と重なる語（en, se, al, lo, la, de, que, una など）は除く
    "spa": set("el los las y por con para es como pero más este esta sus también fue "
               "entre sobre desde".split()),
    # フランス語・イタリア語と重なる語（et, est, non, per など）は除く
    "lat": set("cum quod ut sed quae esse quam enim autem sunt atque sive vel nec neque "
               "etiam quoque itaque ergo igitur idem eius eorum hoc haec quidem tamen".split()),
}


def word_counts(text):
    words = re.findall(r"[a-zà-öø-ÿß]+", text.lower())
    return {lang: sum(1 for w in words if w in sw) for lang, sw in STOPWORDS.items()}


def judge(counts, greek):
    """戻り値: (言語のリスト, 自信があるか, 迷った理由のリスト)"""
    reasons = []
    ranked = sorted(((c, l) for l, c in counts.items()), reverse=True)
    top = ranked[0][0]
    if top < 15:
        langs = []
        reasons.append(T("本文の単語がほとんど読み取れない", "very little readable text"))
    else:
        langs = [l for c, l in ranked if c >= max(8, top * 0.3)]
        borderline = [l for c, l in ranked if 5 <= c < max(8, top * 0.3) and c >= top * 0.15]
        if borderline:
            names = "・".join(lang_name(l) for l in borderline)
            reasons.append(T(f"少しだけ出てくる言語がある（{names}）",
                             f"some text in {', '.join(lang_name(l) for l in borderline)}"))
        if len(langs) > 3:
            reasons.append(T("4言語以上が混在（論集？）", "4+ languages mixed (collection?)"))
            langs = langs[:3]
    if greek >= 20:
        langs.append("grc")
    elif greek >= 1:
        langs.append("grc")
        reasons.append(T(f"ギリシャ文字が少しだけ（{greek}字）", f"only a few Greek letters ({greek})"))
    if not langs:
        langs = list(LANG_ORDER)
    return [l for l in LANG_ORDER if l in langs], not reasons, reasons


# ---------------------------------------------------------------- 加工

def despeckle_pdf(src, dst, min_area=6, pages=None):
    """白黒(1bit)のページ画像から、面積 min_area ピクセル未満の黒い点を消す。
    pages（0始まりの番号のリスト）を指定すると、そのページだけを掃除する。
    文字層と注釈には触れない。戻り値: (掃除した画像の数, 消した点の数)"""
    import cv2
    import numpy as np
    pdf = pikepdf.open(src)
    done, cleaned, removed_total = set(), 0, 0
    targets = pdf.pages if pages is None else [pdf.pages[i] for i in pages]
    for page in targets:
        for raw in page_images(page):
            if raw.objgen in done:
                continue
            done.add(raw.objgen)
            img = PdfImage(raw)
            if img.bits_per_component != 1 or raw.get("/ImageMask", False):
                continue
            try:
                arr = np.array(img.as_pil_image().convert("L"))
            except Exception:
                continue          # 読めない形式の画像はそのまま残す
            black = (arr < 128).astype(np.uint8)
            _, labels, stats, _ = cv2.connectedComponentsWithStats(black, connectivity=8)
            small = stats[:, cv2.CC_STAT_AREA] < min_area
            small[0] = False
            arr[small[labels]] = 255
            removed_total += int(small.sum())
            bits = np.packbits(arr >= 128, axis=1)
            raw.write(zlib.compress(bits.tobytes(), 9), filter=Name.FlateDecode)
            for key in ("/DecodeParms", "/Decode"):
                if key in raw:
                    del raw[key]
            raw.ColorSpace = Name.DeviceGray
            raw.BitsPerComponent = 1
            cleaned += 1
    pdf.save(dst)
    pdf.close()
    return cleaned, removed_total


def strip_annots(src, dst):
    with pikepdf.open(src) as pdf:
        for page in pdf.pages:
            if Name.Annots in page.obj:
                del page.obj[Name.Annots]
        pdf.save(dst)


def copy_annots(src_path, ocr_path, out_path):
    src = pikepdf.open(src_path)
    dst = pikepdf.open(ocr_path)
    if len(src.pages) != len(dst.pages):
        raise RuntimeError(T("ページ数が一致しません（注釈の移植を中止）",
                             "page count mismatch (annotation transfer aborted)"))
    for sp, dp in zip(src.pages, dst.pages):
        if Name.Annots not in sp.obj:
            continue
        new_annots = Array()
        for a in sp.obj.Annots:
            if not a.is_indirect:
                a = src.make_indirect(a)
            if Name.P in a:
                del a[Name.P]
            na = dst.copy_foreign(a)
            na[Name.P] = dp.obj
            new_annots.append(na)
        if Name.Annots in dp.obj:
            for x in dp.obj.Annots:
                new_annots.append(x)
        dp.obj.Annots = new_annots
    dst.save(out_path)
    src.close()
    dst.close()


def binarize(src, dst, threshold=140):
    n = 0
    with pikepdf.open(src) as pdf:
        for page in pdf.pages:
            for raw in page_images(page):
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


def ocrmypdf(*args):
    r = subprocess.run([sys.executable, "-m", "ocrmypdf", *map(str, args)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join(r.stderr.strip().splitlines()[-5:])
        raise RuntimeError(f"ocrmypdf exit {r.returncode}\n{tail}")


def mb(p):
    return Path(p).stat().st_size / 1024 / 1024


def notify(message, title="EuroOCR"):
    def q(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    subprocess.run(["osascript", "-e",
                    f"display notification {q(message)} with title {q(title)} sound name \"Glass\""],
                   capture_output=True)

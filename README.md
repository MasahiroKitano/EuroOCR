# EuroOCR

[日本語](#日本語) ｜ [English](#english)

---

## 日本語

スキャンした欧文の本（古典ギリシャ語・ラテン語を含む）を、検索・コピーできるPDFにするMac用アプリです。

- **ダウンロード**：[Releases](https://github.com/MasahiroKitano/EuroOCR/releases) のページから、最新版の zip をダウンロードしてください。
- **質問・不具合の報告**：[Issues](https://github.com/MasahiroKitano/EuroOCR/issues) へどうぞ（日本語でも英語でもかまいません）。

### 4つのアプリ

| アプリ | 役割 |
|---|---|
| **EuroOCR-Setup** | 必要な部品をインストールする（最初に1回） |
| **EuroOCR** | PDFをドロップすると、見開き分割・白紙の1ページ目の削除・ノイズ除去・傾き補正・言語判定・OCRを行い、元のファイルの隣に「名前_OCR.pdf」を保存する |
| **EuroOCR-Pages** | PDFを1冊ドロップし、指定したページを指定した言語で読み直す（多言語の論集用）。「名前_reOCR.pdf」を保存する |
| **EuroOCR-Resplit** | 見開きの分割がずれて文字が切れたページを直す。「名前_OCR.pdf」をドロップすると窓が開き、元の見開きの画像の上で切る位置をクリックして、その2ページだけを切り直して読み直す（上書き保存） |

対応言語：英語（eng）、ドイツ語（deu）、フランス語（fra）、イタリア語（ita）、スペイン語（spa）、ラテン語（lat）、古典ギリシャ語（grc）

### この道具について

EuroOCR は、新しい OCR エンジンではありません。文字の読み取りには、広く使われているオープンソースの [Tesseract](https://github.com/tesseract-ocr/tesseract) と [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) を使っています。EuroOCR が受け持つのは、古典学などの研究者が欧文の本を自分でスキャンして PDF にするときの、一連の作業をまとめることです。

- 見開きのスキャンを左右のページに分割する
- 白黒スキャンの細かいゴミを消し、傾きを補正する
- 英語・ドイツ語・フランス語・イタリア語・スペイン語に、ラテン語や古典ギリシャ語（多音調表記）が混じる本の言語を判定する
- 多言語の論集を、ページごとに別の言語で読み直す
- 分割の位置がずれたページを、後から手で切り直す
- 付箋・ハイライトを保ち、元のファイルを書き換えない

これらを、PDF をアプリにドロップするだけで行えるようにした道具です。

**動作環境**

- 作者は macOS 27・Apple シリコンの Mac で使っています。Homebrew が対応している、比較的新しい macOS が必要です。Intel の Mac でも動くように作ってありますが、動作は確かめていません。
- セットアップのときにインターネット接続が必要です。
- ディスクの空きが3〜4GBほど必要です（Homebrew、OCR の部品、認識データ）。

### はじめに

#### 1. 「ダウンロード品」の印を外す

インターネットから入手したアプリは、そのままでは開けません（Apple の署名がないため）。最初に一度だけ、次のどちらかを行ってください。

**方法A（おすすめ）：ターミナルで一度に**

「アプリケーション」→「ユーティリティ」→「ターミナル」を開き、次の一行を打ちます（最後に半角スペースを入れる）。続けて、このフォルダ（EuroOCR）をターミナルのウインドウにドラッグし、Return を押します。

```
xattr -dr com.apple.quarantine 
```

何も表示されなければ成功です。中のアプリとスクリプトがすべて開けるようになります。

**方法B：アプリごとに許可する**

1. アプリをダブルクリックします。「開いていません」と出たら「完了」を押します（「ゴミ箱に入れる」は押さない）。
2. 「システム設定」→「プライバシーとセキュリティ」を開き、下のほうの「このまま開く」を押して、パスワードを入力します。
3. 確認の画面で「開く」を押します。4つのアプリそれぞれで、初回に一度ずつ行います。

「壊れているため開けません」と出た場合も、方法Aで直ります。macOS 14 以前では、右クリック →「開く」でも開けます。

#### 2. セットアップ

**EuroOCR-Setup** を開きます。初回は20〜40分かかります。Homebrew が入っていなければ Mac のパスワードを聞かれます（入力しても画面には表示されません）。「セットアップが完了しました」と出れば準備完了です。何度実行しても安全です（そろっている部品は飛ばします）。

セットアップが済むまでは、EuroOCR-Setup と scripts フォルダを同じフォルダに置いたままにしてください。

#### 3. 使う

**EuroOCR**、**EuroOCR-Pages**、**EuroOCR-Resplit** は、「アプリケーション」フォルダや Dock など、どこへ移してもかまいません。PDFをアプリのアイコンにドロップします（ダブルクリックするとファイルを選ぶ画面が出ます）。

初回は次の許可を求められることがあります。どちらも「OK」か「許可」を押してください。

- 「"EuroOCR"が"ターミナル"を制御しようとしています」
- 「"ターミナル"が"書類"フォルダ（など）内のファイルにアクセスしようとしています」

誤って拒否した場合は、「システム設定」→「プライバシーとセキュリティ」→「オートメーション」または「ファイルとフォルダ」で、ターミナルをオンにします。

**ホームフォルダ内の `~/EuroOCR` フォルダは、場所も名前も変えないでください。** 部品・認識データ・ログが入っています。

### EuroOCR の動き

- ページの半分以上が横長なら見開きとみなして左右に分割し、1ページ目が白紙なら削除します。
- 文字層のないスキャンには、ノイズ除去（白黒画像の小さな点を消す）と傾き補正をかけます。
- 5ページを試し読みして言語を判定します。自信がないときだけ確認画面が出ます（「全冊で確認」も選べます）。
- 全冊の判定が済んでから、続けてOCRします。そこから先は操作不要です。終わると通知と音で知らせます。
- 元のファイルは書き換えません。付箋・ハイライトは引き継ぎます。日本語中心の本と、元から文字のある電子版は処理しません。
- 途中で止めるには、ターミナルで control + C を押します。

ドロップした後の最初の画面で、次の指定を選べます（複数選択可。何も選ばなくてもかまいません）。

- **全冊で言語の確認画面を出す**：自信のある本でも、毎回言語を確かめる。
- **ギリシャ語を必ず加える**：試し読みでギリシャ文字が見つからなくても、古典ギリシャ語を加えて読む。ギリシャ語の引用がまばらな本に。
- **強制OCR**：種類に関係なく、全ページを作り直して読み直す。元から文字がある電子版でギリシャ語が化けているものなどに（日本語中心の本は除く）。

すでに OCR されていてギリシャ語が化けている本は、何も指定しなくても、種類に応じて読み直します（見えない文字の層は入れ替え、ClearScan や FineReader で読まれたものは作り直し）。

### EuroOCR-Pages の指定

```
1-40: deu; 41-85: fra+grc; 86-120: eng+lat
```

「ページ: 言語」を `;` で区切ります。ページは `5`、`5-12`、`5-12,20` のように書きます。言語は `+` でつなぎます。日本語入力のまま打った「：」「；」「＋」「〜」や全角の数字も使えます。

### EuroOCR-Resplit の使い方

1. 文字が切れているページを含む「名前_OCR.pdf」を **EuroOCR-Resplit** にドロップします。窓が開きます。
2. 「直したいページ」の欄にページ番号を入れて「表示」を押します。そのページを含む元の見開きが表示されます（「◀ 前の見開き」「次の見開き ▶」で移れます）。
3. 青い点線が今の切れ目です。新しく切りたい位置（ノドの余白）をクリックすると赤い線が出ます。← → キーで微調整できます（shift を押しながらだと大きく動きます）。
4. 読み直す言語を確かめ（2ページの今の文字から推定した言語に印が付いています）、「切り直して読み直す（上書き保存）」を押します。
5. 終わると画像が新しい切れ目で表示し直されます。窓を開いたまま、続けて別のページも直せます。

- 切り直しは、同じフォルダにある元のスキャン（「名前.pdf」）から行い、新しく切った2ページにノイズ除去・傾き補正・OCRをかけ直します。元のスキャンを移動・削除しないでください。別の場所にある場合は「元のファイルを選ぶ…」で指定できます。
- 元のスキャンが見つからないときは、OCR済みの2ページをくっつけて切り直します。最初のOCRで左右のページを別々に傾き補正したため、つなぎ目で行が上下に食い違うことがありますが、この段差は自動で測って合わせます。はみ出した語の高さが行と合っていないときは、↑ ↓ キーで右ページを上下に動かして合わせてから切り直してください。
- ファイルは上書き保存されます。上書き前の版は `~/EuroOCR/backup` に残ります（新しいものから30個）。
- ほかのアプリで開いていて保存していない変更（付箋など）がある場合は、先に保存してください。
- 付箋・ハイライトは位置に応じて左右のページに振り分け直します。
- 切り直した2ページは、幅が左右で少し違うページになります。

### アプリを作り直す

`.applescript` は4つのアプリの元ファイルです。中身を変えたときは、ターミナルに `bash ` と打って `build_apps.command` をドラッグし、Return を押すとアプリを作り直せます。

### 置き場所

- `~/EuroOCR/`：スクリプト、認識データ、Python の環境
- `~/EuroOCR/logs/EuroOCR_log.txt`：処理の記録
- `~/EuroOCR/backup/`：EuroOCR-Resplit で上書きする前の版

### 使っている部品

Tesseract、OCRmyPDF、Ghostscript、pikepdf、OpenCV、Homebrew（EuroOCR-Setup が利用者の Mac にインストールします）

### 限界と注意

- 文字の読み取りの精度は、Tesseract の精度で決まります。古典ギリシャ語、特に小さな活字・気息記号・アクセント・下書きのイオタには誤認識が残ります。本文をそのまま引用に使うときは、必ず原本で確かめてください。
- 画質の悪いスキャン（解像度が200dpi未満、強い傾き、ゆがみ）では、精度が大きく落ちます。300dpi 前後の白黒またはグレーのスキャンを想定しています。
- 言語の自動判定は、数ページの試し読みにもとづく推定です。外れることがあるので、判定に自信がないときは確認画面が出ます。
- 見開きの分割は、ページの中央で切ります。スキャンのときに本の中心がずれていると、文字が切れることがあります。その場合は EuroOCR-Resplit で直せます。
- 個人が作った道具を、無保証で公開しています。質問や不具合の報告は [Issues](https://github.com/MasahiroKitano/EuroOCR/issues) で受け付けますが、対応できるとは限りません。
- macOS や Homebrew の更新によって、将来動かなくなる可能性があります。

### ライセンス

MIT ライセンスです。無料で、誰でも自由に使用・複製・改変・再配布できます。再配布するときは、著作権表示と `LICENSE` ファイルの文面を残してください。無保証です。作者は、このソフトウェアの使用によって生じたいかなる損害（ファイルの上書きを含む）についても責任を負いません。正式なライセンス文は `LICENSE`（英語）です。

Copyright (c) 2026 Masahiro Kitano（北野雅弘）

EuroOCR は下記の部品を同梱していません。EuroOCR-Setup が、利用者の Mac に Homebrew と pip でインストールします。各部品には、それぞれのライセンスが適用されます。

| 部品 | ライセンス |
|---|---|
| Tesseract OCR、認識データ（tessdata） | Apache License 2.0 |
| OCRmyPDF | Mozilla Public License 2.0 |
| pikepdf | Mozilla Public License 2.0 |
| Ghostscript | GNU Affero General Public License v3（外部のコマンドとして呼び出すだけ） |
| OpenCV | Apache License 2.0 |
| Pillow | MIT-CMU License |
| NumPy | BSD License |
| jbig2enc / jbig2dec | Apache License 2.0 / GNU Affero General Public License v3 |
| pngquant | GNU General Public License v3 |
| Python、Tcl/Tk（python-tk） | Python Software Foundation License、Tcl/Tk License |
| Homebrew | BSD 2-Clause License |

---

## English

Mac apps that turn scanned European-language books (including Ancient Greek and Latin) into searchable PDFs.

- **Download**: get the zip of the latest version from the [Releases](https://github.com/MasahiroKitano/EuroOCR/releases) page.
- **Questions and bug reports**: please use [Issues](https://github.com/MasahiroKitano/EuroOCR/issues) (Japanese or English).

### The four apps

| App | What it does |
|---|---|
| **EuroOCR-Setup** | Installs everything needed (run once first) |
| **EuroOCR** | Drop PDFs to split two-page spreads, remove a blank first page, despeckle, deskew, detect the languages and OCR. Saves “name_OCR.pdf” next to the original |
| **EuroOCR-Pages** | Drop one PDF to re-OCR chosen pages with chosen languages (for multilingual collections). Saves “name_reOCR.pdf” |
| **EuroOCR-Resplit** | Fixes split pages that cut through text. Drop a “name_OCR.pdf” to open a window, click the new cut on an image of the original spread, and re-cut and re-OCR just those two pages (overwrites the file) |

Languages: English (eng), German (deu), French (fra), Italian (ita), Spanish (spa), Latin (lat), Ancient Greek (grc)

### About this tool

EuroOCR is not a new OCR engine. Text recognition is done by the widely used open-source [Tesseract](https://github.com/tesseract-ocr/tesseract) and [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF). What EuroOCR does is bring together the steps that scholars in classics and related fields go through when they scan European-language books into PDFs themselves:

- splitting two-page spread scans into single pages
- removing specks from black-and-white scans and straightening skewed pages
- detecting the languages of books that mix English, German, French, Italian or Spanish with Latin or polytonic Ancient Greek
- re-reading multilingual collections page range by page range in different languages
- re-cutting pages whose split went wrong, by hand, afterwards
- keeping notes and highlights, and never modifying the original file

All of this happens by dropping a PDF onto an app.

**Requirements**

- Developed and used on macOS 27 with Apple silicon. A reasonably recent macOS supported by Homebrew is required. It is written to work on Intel Macs too, but this has not been tested.
- An internet connection during setup
- About 3–4 GB of free disk space (Homebrew, OCR tools, language data)

### Getting started

#### 1. Remove the download quarantine

Apps downloaded from the internet won’t open as-is (they are not signed by Apple). Do one of the following once.

**Option A (recommended): all at once in Terminal**

Open Applications → Utilities → Terminal and type the line below (with a trailing space). Then drag this EuroOCR folder into the Terminal window and press Return.

```
xattr -dr com.apple.quarantine 
```

No output means success. All apps and scripts in the folder can now be opened.

**Option B: allow each app**

1. Double-click the app. When macOS says it was not opened, click “Done” (not “Move to Trash”).
2. Open System Settings → Privacy & Security, click “Open Anyway” near the bottom and enter your password.
3. Click “Open” to confirm. Repeat once for each of the four apps.

If macOS says the app “is damaged”, Option A fixes it too. On macOS 14 or earlier, right-click → Open also works.

#### 2. Setup

Open **EuroOCR-Setup**. The first run takes 20–40 minutes. If Homebrew is missing you will be asked for your Mac password (it is not shown as you type). Setup is done when “Setup complete” appears. It is safe to run again (existing parts are skipped).

Keep EuroOCR-Setup and the scripts folder together in the same folder until setup is done.

#### 3. Use

You can move **EuroOCR**, **EuroOCR-Pages** and **EuroOCR-Resplit** anywhere (the Applications folder, the Dock, …). Drop PDFs onto the app icon (or double-click it to choose files).

On first use macOS may ask for these permissions; click “OK” or “Allow”.

- “EuroOCR wants to control Terminal”
- “Terminal would like to access files in your Documents folder” (or a similar folder)

If you declined by mistake, turn Terminal on in System Settings → Privacy & Security → Automation or Files and Folders.

**Do not move or rename the `~/EuroOCR` folder in your home folder.** It holds the tools, language data and logs.

### How EuroOCR works

- If at least half of the pages are landscape, the book is treated as two-page spreads and split; a blank first page is removed.
- Scans without a text layer are despeckled (small dots in black-and-white images are removed) and deskewed.
- Five pages are sampled to detect the languages; a dialog appears only when unsure (or for every book, if you choose).
- OCR starts after all books are analyzed; no further input is needed. A notification sounds when done.
- Originals are never modified. Notes and highlights are kept. Mainly-Japanese and born-digital PDFs are skipped.
- To stop, press control + C in Terminal.

After dropping files, the first dialog offers these options (choose any, or none):

- **Confirm the languages for every book**: check the languages even when the detection is confident.
- **Always include Ancient Greek**: read with Ancient Greek even if no Greek letters are found in the sample pages. Useful for books with scattered Greek quotations.
- **Forced OCR**: rebuild and re-read every page regardless of type, e.g. born-digital PDFs whose Greek is garbled (mainly-Japanese books are still skipped).

Books that were already OCRed with garbled Greek are re-read without any option, according to their type (hidden text layers are replaced; ClearScan and FineReader output is rebuilt).

### Page spec for EuroOCR-Pages

```
1-40: deu; 41-85: fra+grc; 86-120: eng+lat
```

Write “pages: languages”, separated by `;`. Pages look like `5`, `5-12` or `5-12,20`. Join languages with `+`.

### Using EuroOCR-Resplit

1. Drop the “name_OCR.pdf” that has a badly split page onto **EuroOCR-Resplit**. A window opens.
2. Enter the page number to fix and click “Show”. The original spread containing that page appears (“◀ Prev spread” / “Next spread ▶” move between spreads).
3. The blue dotted line is the current cut. Click where the new cut should be (in the gutter margin); a red line appears. Fine-tune with ← → (hold shift for bigger steps).
4. Check the languages (pre-selected from the current text of the two pages) and click “Re-split and re-OCR (overwrite)”.
5. When done, the image is shown again with the new cut. You can keep the window open and fix other pages.

- The pages are re-cut from the original scan (“name.pdf”) in the same folder, and the two new pages are despeckled, deskewed and OCRed again. Do not move or delete the original scan; if it is elsewhere, use “Choose original…”.
- If the original scan is not found, the two OCRed pages are joined and re-cut instead. Because the first OCR deskewed the two pages separately, lines may not meet at the seam; this step is measured and corrected automatically. If the cut-off words still do not line up, move the right page with ↑ ↓ before re-splitting.
- The file is overwritten. The previous version is kept in `~/EuroOCR/backup` (the 30 most recent).
- If the file is open in another app with unsaved changes (notes etc.), save them first.
- Notes and highlights are reassigned to the left or right page according to their position.
- The two re-split pages will have slightly different widths.

### Rebuilding the apps

The `.applescript` files are the sources of the four apps. After editing them, type `bash ` in Terminal, drag `build_apps.command` into the window and press Return to rebuild the apps.

### Files

- `~/EuroOCR/`: scripts, language data, Python environment
- `~/EuroOCR/logs/EuroOCR_log.txt`: processing log
- `~/EuroOCR/backup/`: versions before EuroOCR-Resplit overwrote them

### Built on

Tesseract, OCRmyPDF, Ghostscript, pikepdf, OpenCV, Homebrew (installed on your Mac by EuroOCR-Setup)

### Limitations

- Recognition accuracy is that of Tesseract. Errors remain in Ancient Greek, especially with small type, breathings, accents and iota subscript. Always check the original before quoting the recognized text.
- Accuracy drops sharply for poor scans (below about 200 dpi, strong skew, warping). Scans of about 300 dpi, black-and-white or grayscale, are assumed.
- Language detection is an estimate from a few sample pages and can be wrong; a dialog appears when it is unsure.
- Spreads are split at the middle of the page. If the book was off-center when scanned, text may be cut; EuroOCR-Resplit can fix such pages.
- This is a personal tool published without warranty. Questions and bug reports are welcome on [Issues](https://github.com/MasahiroKitano/EuroOCR/issues), but may not always be answered.
- Future macOS or Homebrew updates may stop it from working.

### License

MIT License. Free for anyone to use, copy, modify and redistribute. Keep the copyright notice and the text of `LICENSE` when redistributing. Provided “as is”, without warranty of any kind; the author is not liable for any damage arising from its use (including overwritten files). The authoritative text is `LICENSE`.

Copyright (c) 2026 Masahiro Kitano

EuroOCR does not bundle the components below; EuroOCR-Setup installs them on your Mac with Homebrew and pip. Each component is covered by its own license.

| Component | License |
|---|---|
| Tesseract OCR, language data (tessdata) | Apache License 2.0 |
| OCRmyPDF | Mozilla Public License 2.0 |
| pikepdf | Mozilla Public License 2.0 |
| Ghostscript | GNU Affero General Public License v3 (only called as an external command) |
| OpenCV | Apache License 2.0 |
| Pillow | MIT-CMU License |
| NumPy | BSD License |
| jbig2enc / jbig2dec | Apache License 2.0 / GNU Affero General Public License v3 |
| pngquant | GNU General Public License v3 |
| Python, Tcl/Tk (python-tk) | Python Software Foundation License, Tcl/Tk License |
| Homebrew | BSD 2-Clause License |

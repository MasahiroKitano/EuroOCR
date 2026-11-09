-- Copyright (c) 2026 Masahiro Kitano (北野雅弘)
-- SPDX-License-Identifier: MIT
-- EuroOCR ③：PDFを1冊ドロップし、指定したページを指定した言語で読み直す（多言語の論集用）
-- EuroOCR ③: drop one PDF and re-OCR chosen pages with chosen languages (multilingual books)

property pyPath : "~/EuroOCR/venv/bin/python3"
property scriptPath : "~/EuroOCR/reocr_pages.py"

on isJa()
	return (user locale of (system info)) starts with "ja"
end isJa

on L(ja, en)
	if isJa() then return ja
	return en
end L

on run
	set f to choose file with prompt L("読み直すPDFを1冊選んでください", "Choose one PDF to re-OCR") of type {"com.adobe.pdf"}
	processItems({f})
end run

on open theItems
	processItems(theItems)
end open

on processItems(theItems)
	try
		do shell script "test -x " & pyPath & " && test -f " & scriptPath
	on error
		display dialog L("EuroOCR の部品が見つかりません。先に「EuroOCR-Setup」を実行してください。", "EuroOCR is not set up yet. Please run “EuroOCR-Setup” first.") buttons {"OK"} default button 1 with title "EuroOCR-Pages" with icon caution
		return
	end try

	set target to missing value
	repeat with anItem in theItems
		set p to POSIX path of anItem
		if (p ends with ".pdf" or p ends with ".PDF") and target is missing value then set target to p
	end repeat
	if target is missing value then
		display dialog L("PDFファイルを1冊ドロップしてください。", "Please drop one PDF file.") buttons {"OK"} default button 1 with title "EuroOCR-Pages" with icon caution
		return
	end if
	if (count of theItems) > 1 then
		display dialog L("一度に処理できるのは1冊です。最初のPDFだけを処理します。", "Only one book at a time; the first PDF will be processed.") buttons {L("やめる", "Cancel"), "OK"} default button 2 cancel button 1 with title "EuroOCR-Pages"
	end if

	set pageCount to do shell script pyPath & " -c " & quoted form of "import sys, pikepdf; print(len(pikepdf.open(sys.argv[1]).pages))" & " " & quoted form of target
	set fname to do shell script "basename " & quoted form of target

	set helpText to L(fname & "（全 " & pageCount & " ページ）" & return & return & "「ページ: 言語」を ; で区切って入力してください。" & return & "言語: eng 英 / deu 独 / fra 仏 / ita 伊 / spa 西 / lat ラテン / grc ギリシャ（+でつなぐ）" & return & return & "例: 1-40: deu; 41-85: fra+grc; 86-120: eng+lat", fname & " (" & pageCount & " pages)" & return & return & "Enter “pages: languages”, separated by ;" & return & "Languages: eng / deu / fra / ita / spa / lat / grc (join with +)" & return & return & "Example: 1-40: deu; 41-85: fra+grc; 86-120: eng+lat")
	set r to display dialog helpText default answer "" buttons {L("キャンセル", "Cancel"), L("読み直す", "Re-OCR")} default button 2 cancel button 1 with title "EuroOCR-Pages"
	set spec to text returned of r
	if spec is "" then return

	set cmd to "caffeinate -i " & pyPath & " " & scriptPath & " " & quoted form of target & " --spec " & quoted form of spec
	tell application "Terminal"
		activate
		do script cmd
	end tell
end processItems

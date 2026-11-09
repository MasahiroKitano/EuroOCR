-- Copyright (c) 2026 Masahiro Kitano (北野雅弘)
-- SPDX-License-Identifier: MIT
-- EuroOCR ①：PDFをドロップすると、1冊ずつ 見開き分割 → ノイズ除去 → 傾き補正 → OCR
-- EuroOCR ①: drop PDFs to split spreads, despeckle, deskew and OCR them one by one

property pyPath : "~/EuroOCR/venv/bin/python3"
property scriptPath : "~/EuroOCR/euro_ocr.py"

on isJa()
	return (user locale of (system info)) starts with "ja"
end isJa

on L(ja, en)
	if isJa() then return ja
	return en
end L

on run
	set theFiles to choose file with prompt L("OCRするPDFを選んでください（複数選択可）", "Choose the PDFs to OCR (you can choose several)") of type {"com.adobe.pdf"} with multiple selections allowed
	processItems(theFiles)
end run

on open theItems
	processItems(theItems)
end open

on processItems(theItems)
	try
		do shell script "test -x " & pyPath & " && test -f " & scriptPath
	on error
		display dialog L("EuroOCR の部品が見つかりません。先に「EuroOCR-Setup」を実行してください。", "EuroOCR is not set up yet. Please run “EuroOCR-Setup” first.") buttons {"OK"} default button 1 with title "EuroOCR" with icon caution
		return
	end try

	set pdfArgs to ""
	set pdfCount to 0
	set folderNames to {}
	set otherNames to {}
	repeat with anItem in theItems
		set p to POSIX path of anItem
		if p ends with "/" then
			set end of folderNames to name of (info for anItem)
		else if p ends with ".pdf" or p ends with ".PDF" then
			set pdfArgs to pdfArgs & " " & quoted form of p
			set pdfCount to pdfCount + 1
		else
			set end of otherNames to name of (info for anItem)
		end if
	end repeat

	if folderNames is not {} or otherNames is not {} then
		set AppleScript's text item delimiters to ", "
		set msg to ""
		if folderNames is not {} then set msg to msg & L("フォルダは処理しません: ", "Folders are not processed: ") & (folderNames as text) & return
		if otherNames is not {} then set msg to msg & L("PDFではないので飛ばします: ", "Not PDF, skipped: ") & (otherNames as text) & return
		set AppleScript's text item delimiters to ""
		if pdfCount = 0 then
			display dialog msg & return & L("PDFファイルをドロップしてください。", "Please drop PDF files.") buttons {"OK"} default button 1 with title "EuroOCR" with icon caution
			return
		end if
		display dialog msg buttons {L("やめる", "Cancel"), L("PDFだけ処理する", "Process the PDFs")} default button 2 cancel button 1 with title "EuroOCR" with icon caution
	end if

	-- 指定を選ぶ（何も選ばなければ通常の処理）
	set optAsk to L("全冊で言語の確認画面を出す", "Confirm the languages for every book")
	set optGreek to L("ギリシャ語を必ず加える", "Always include Ancient Greek")
	set optForce to L("強制OCR（全ページ作り直す。ギリシャ語が化けた電子版などに）", "Forced OCR (rebuild all pages; e.g. digital PDFs with garbled Greek)")
	set promptText to L((pdfCount as text) & " 冊をOCRします。" & return & "必要な指定を選んでください（⌘クリックで複数選択。何も選ばなくてもかまいません）。" & return & return & "何も選ばない場合：言語の確認は自信がないときだけ、ギリシャ語は見つかったときだけ加えます。", "OCR " & (pdfCount as text) & " book(s)." & return & "Choose any options (⌘-click for several; choosing none is fine)." & return & return & "With no options: languages are confirmed only when unsure, and Greek is added only when found.")
	set picked to choose from list {optAsk, optGreek, optForce} with title "EuroOCR" with prompt promptText OK button name L("OCR開始", "Start OCR") cancel button name L("キャンセル", "Cancel") with multiple selections allowed and empty selection allowed
	if picked is false then return
	set opt to ""
	if picked contains optAsk then set opt to opt & " --ask-always"
	if picked contains optGreek then set opt to opt & " --greek"
	if picked contains optForce then set opt to opt & " --force"

	set cmd to "caffeinate -i " & pyPath & " " & scriptPath & pdfArgs & opt
	tell application "Terminal"
		activate
		do script cmd
	end tell
end processItems

-- Copyright (c) 2026 Masahiro Kitano (北野雅弘)
-- SPDX-License-Identifier: MIT
-- EuroOCR ④：分割の切り直し。PDFを1冊ドロップすると、ページを選び、切る位置をクリックで決めて、
--            その2ページだけを読み直す窓が開く（上書き保存）
-- EuroOCR ④: re-split a page pair. Drop one PDF to open a window where you pick the pages,
--            click the new cut and re-OCR just those two pages (overwrites the file)

property pyPath : "~/EuroOCR/venv/bin/python3"
property scriptPath : "~/EuroOCR/resplit.py"

on isJa()
	return (user locale of (system info)) starts with "ja"
end isJa

on L(ja, en)
	if isJa() then return ja
	return en
end L

on run
	set f to choose file with prompt L("切り直すPDFを1冊選んでください", "Choose one PDF to re-split") of type {"com.adobe.pdf"}
	processItems({f})
end run

on open theItems
	processItems(theItems)
end open

on processItems(theItems)
	try
		do shell script "test -x " & pyPath & " && test -f " & scriptPath & " && " & pyPath & " -c 'import tkinter'"
	on error
		display dialog L("EuroOCR の部品が見つからないか、古くなっています。「EuroOCR-Setup」をもう一度実行してください。", "EuroOCR is not set up or is out of date. Please run “EuroOCR-Setup” again.") buttons {"OK"} default button 1 with title "EuroOCR-Resplit" with icon caution
		return
	end try

	set target to missing value
	repeat with anItem in theItems
		set p to POSIX path of anItem
		if (p ends with ".pdf" or p ends with ".PDF") and target is missing value then set target to p
	end repeat
	if target is missing value then
		display dialog L("PDFファイルを1冊ドロップしてください。", "Please drop one PDF file.") buttons {"OK"} default button 1 with title "EuroOCR-Resplit" with icon caution
		return
	end if

	-- 窓は別に開くので、このアプリはすぐに終わる
	do shell script "nohup " & pyPath & " " & scriptPath & " " & quoted form of target & " > /dev/null 2>&1 &"
end processItems

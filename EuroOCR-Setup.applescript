-- Copyright (c) 2026 Masahiro Kitano (北野雅弘)
-- SPDX-License-Identifier: MIT
-- EuroOCR ②：必要な部品をインストールし、スクリプトを ~/EuroOCR に置く
-- EuroOCR ②: install the required tools and put the scripts in ~/EuroOCR

on isJa()
	return (user locale of (system info)) starts with "ja"
end isJa

on L(ja, en)
	if isJa() then return ja
	return en
end L

on run
	-- このアプリと同じフォルダにある scripts フォルダを探す
	set myFolder to POSIX path of ((path to me as text) & "::")
	set srcDir to myFolder & "scripts"
	try
		do shell script "test -f " & quoted form of (srcDir & "/install.sh")
	on error
		-- 見つからないとき（ダウンロード直後で別の場所から起動された場合など）は選んでもらう
		set promptText to L("EuroOCR の「scripts」フォルダを選んでください", "Choose the EuroOCR “scripts” folder")
		set pickedFolder to choose folder with prompt promptText
		set srcDir to POSIX path of pickedFolder
		if srcDir ends with "/" then
			set srcDir to text 1 thru -2 of srcDir
		end if
		try
			do shell script "test -f " & quoted form of (srcDir & "/install.sh")
		on error
			display dialog L("選んだフォルダに install.sh がありません。", "install.sh is not in that folder.") buttons {"OK"} default button 1 with title "EuroOCR-Setup" with icon caution
			return
		end try
	end try

	display dialog L("EuroOCR に必要な部品をインストールします。" & return & return & "・Homebrew（なければ。Mac のパスワードを聞かれます）" & return & "・Tesseract、Ghostscript など" & return & "・7言語の認識データ（約150MB）" & return & return & "初回は20〜40分ほどかかります。すでにある部品は飛ばします。", "This installs what EuroOCR needs:" & return & return & "• Homebrew (if missing; asks for your Mac password)" & return & "• Tesseract, Ghostscript, etc." & return & "• language data for 7 languages (about 150 MB)" & return & return & "The first run takes 20–40 minutes. Existing parts are skipped.") buttons {L("キャンセル", "Cancel"), L("インストール", "Install")} default button 2 cancel button 1 with title "EuroOCR-Setup"

	tell application "Terminal"
		activate
		do script "bash " & quoted form of (srcDir & "/install.sh") & " " & quoted form of srcDir
	end tell
end run

$ErrorActionPreference = 'Stop'
if (!$env:OCR_PREFIX) { throw 'OCR_PREFIX must point to MSYS2 UCRT64' }
python -m PyInstaller --noconfirm --clean --onedir --windowed --name ElectroReview --collect-all pypdfium2 --collect-all pypdfium2_raw --collect-all reportlab app.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
$dest = 'dist/ElectroReview'
New-Item -ItemType Directory -Force "$dest/ocr" | Out-Null
Copy-Item "$env:OCR_PREFIX/bin/tesseract.exe" "$dest/ocr/"
Copy-Item "$env:OCR_PREFIX/bin/*.dll" "$dest/ocr/"
Copy-Item "$env:OCR_PREFIX/share/tessdata" "$dest/ocr/" -Recurse
Copy-Item "$env:OCR_PREFIX/share/licenses" "$dest/ocr/" -Recurse
Copy-Item 'msys2-packages.txt' "$dest/ocr/"
Copy-Item 'README.md','START-HERE.txt','THIRD-PARTY.md' $dest
python -m pip freeze | Out-File "$dest/python-packages.txt" -Encoding utf8
foreach ($required in @('tesseract.exe','tessdata/rus.traineddata','tessdata/eng.traineddata','tessdata/configs/tsv')) {
    if (!(Test-Path "$dest/ocr/$required")) { throw "Missing OCR file: $required" }
}
Get-ChildItem $dest -File -Recurse | ForEach-Object {
    $hash = Get-FileHash $_.FullName -Algorithm SHA256
    "$($hash.Hash)  $($_.FullName.Substring((Resolve-Path $dest).Path.Length + 1))"
} | Set-Content "$dest/SHA256SUMS.txt"

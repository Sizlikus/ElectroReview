# Сторонние компоненты и источники

Python: https://www.python.org/psf/license/
Tcl/Tk: https://www.tcl.tk/software/tcltk/license.html
pypdfium2 и PDFium: https://github.com/pypdfium2-team/pypdfium2
pypdf: https://github.com/py-pdf/pypdf
ReportLab: https://www.reportlab.com/opensource/
Pillow: https://github.com/python-pillow/Pillow
PyInstaller: https://pyinstaller.org/en/stable/license.html
Tesseract: https://github.com/tesseract-ocr/tesseract (Apache-2.0)
MSYS2 Windows build: https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-tesseract-ocr
Russian model package: https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-tesseract-data-rus
MSYS2 package recipes/source links: https://github.com/msys2/MINGW-packages
MSYS2 setup action: https://github.com/msys2/setup-msys2

Сборка копирует каталог лицензий MSYS2 вместе с OCR, сохраняет список установленных
пакетов, версии Python-зависимостей и SHA-256 файлов. Не удаляйте уведомления из
распространяемой папки. Зависимости MSYS2 устанавливаются из подписанного репозитория;
их точные версии фиксируются в msys2-packages.txt каждого запуска.

Архив исходников не содержит моделей или Windows-бинарников. Они добавляются в
GitHub Actions. Перед публичным выпуском требуется проверка лицензий фактической
сборки, включая условия распространения транзитивных DLL.

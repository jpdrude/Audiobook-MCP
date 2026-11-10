@echo off
rem Usage: render_book.bat INPUT_DIR OUTPUT_DIR [extra options, e.g. --album "Title" --artist "Name"]
rem Double-click with no arguments to be prompted for the folders.
setlocal
call "%~dp0.venv\Scripts\activate.bat"
if "%~1"=="" (
  set /p INDIR=Input folder with HTML chapters:
  set /p OUTDIR=Output folder for MP3 files:
  python "%~dp0render_book.py" "%INDIR%" "%OUTDIR%"
) else (
  python "%~dp0render_book.py" %*
)
pause

@echo off
REM Builds dist\g-code_perimeter_generator.exe (needs Python 3 installed from python.org)
python -m pip install --upgrade pyinstaller -r requirements.txt || goto :error
python -m unittest discover -s tests || goto :error
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name g-code_perimeter_generator ^
  --icon iconn.ico ^
  --add-data "iconn.ico;." ^
  --add-data "logo.png;." ^
  --collect-data sv_ttk ^
  g-code_perimeter_generator.py || goto :error
echo.
echo Done: dist\g-code_perimeter_generator.exe
pause
exit /b 0
:error
echo Build failed.
pause
exit /b 1

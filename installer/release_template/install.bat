@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -3 install.py %* & goto end)
python install.py %*
:end
pause

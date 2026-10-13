@echo off
cd /d "%~dp0.."
set /p NUM=Your own phone number: 
set /p PORT=AT serial port (e.g. COM5): 
python ec20_uac_call.py --tone --exclusive --port %PORT% --dial %NUM%
pause

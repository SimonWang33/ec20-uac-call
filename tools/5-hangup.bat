@echo off
cd /d "%~dp0.."
set /p PORT=AT serial port (e.g. COM5): 
python ec20_uac_call.py --port %PORT% --hangup
pause

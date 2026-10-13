@echo off
cd /d "%~dp0.."
echo NOTE: run this WHILE a call is up.
python ec20_uac_call.py --rec 5
pause

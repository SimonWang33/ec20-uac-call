@echo off
cd /d "%~dp0.."
echo TIP: for Chinese text run this in PowerShell instead:
echo   python ec20_uac_call.py --say "your text" --port COM5 --dial 1xxxxxxxxxx
set /p TXT=Text to speak (ASCII only inside a .bat): 
set /p NUM=Your own phone number: 
set /p PORT=AT serial port (e.g. COM5): 
python ec20_uac_call.py --say "%TXT%" --port %PORT% --dial %NUM%
pause

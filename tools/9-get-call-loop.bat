@echo off
cd /d "%~dp0.."
echo Checking the phone mailbox every 60 seconds. Press Ctrl+C to stop.
python phone_mailbox.py --loop 60
pause

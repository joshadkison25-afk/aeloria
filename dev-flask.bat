@echo off
REM Flask only (no Next — home map iframe will be blank unless Next is already on 3000).
REM Full stack: npm run dev   or   double-click dev-all.bat
set FLASK_DEBUG=1
python app.py

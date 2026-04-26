@echo off
REM Flask only. For map + app together: npm run dev:all  or  double-click dev-all.bat
REM Local dev: enable Werkzeug auto-reload on Python file changes
set FLASK_DEBUG=1
python app.py

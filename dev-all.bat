@echo off
cd /d "%~dp0"
if not exist "node_modules" (
  echo Running npm install...
  call npm install
)
echo One command: Next + Flask. Site: http://127.0.0.1:5000
call npm run dev:all
pause

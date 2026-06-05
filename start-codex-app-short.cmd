@echo off
setlocal

rem Start Codex Desktop App in this project with the normal short context.
chcp 65001 >nul 2>&1

for %%I in ("%~dp0.") do set "WORKDIR=%%~fI"
set "CONTEXT_WINDOW=272000"
set "AUTO_COMPACT=240000"
set "CODEX_EXE=%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe"

if not exist "%CODEX_EXE%" (
  set "CODEX_EXE="
  for /f "delims=" %%C in ('where codex 2^>nul') do if not defined CODEX_EXE set "CODEX_EXE=%%C"
)

if not defined CODEX_EXE (
  echo [ERROR] codex.exe nicht gefunden. Ist Codex installiert und im PATH?
  pause
  exit /b 1
)

echo [INFO] Starte Codex App - Short Context
echo [INFO] Workdir: %WORKDIR%
echo [INFO] Context: %CONTEXT_WINDOW%, Auto-Compact: %AUTO_COMPACT%

start "Codex App [short]" "%CODEX_EXE%" -c model_context_window=%CONTEXT_WINDOW% -c model_auto_compact_token_limit=%AUTO_COMPACT% app "%WORKDIR%"

endlocal
exit /b 0

@echo off
setlocal

rem Start Codex CLI in this project with the normal short context.
chcp 65001 >nul 2>&1
set "LANG=en_US.UTF-8"
set "LC_ALL=en_US.UTF-8"
set "LESSCHARSET=utf-8"
set "PYTHONUTF8=1"

for %%I in ("%~dp0.") do set "WORKDIR=%%~fI"
set "CONTEXT_WINDOW=272000"
set "AUTO_COMPACT=240000"
set "CODEX_EXE=%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe"
set "LOCAL_PWSH=C:\Program Files\PowerShell\7\pwsh.exe"

if not exist "%CODEX_EXE%" (
  set "CODEX_EXE="
  for /f "delims=" %%C in ('where codex 2^>nul') do if not defined CODEX_EXE set "CODEX_EXE=%%C"
)

if not defined CODEX_EXE (
  echo [ERROR] codex.exe nicht gefunden. Ist Codex installiert und im PATH?
  pause
  exit /b 1
)

set "_CALLER="
for /f %%N in ('powershell -noprofile -c "$p=(Get-CimInstance Win32_Process -Filter ('ProcessId='+$PID)).ParentProcessId;$p=(Get-CimInstance Win32_Process -Filter ('ProcessId='+$p)).ParentProcessId;$p=(Get-CimInstance Win32_Process -Filter ('ProcessId='+$p)).ParentProcessId;(Get-Process -Id $p).ProcessName" 2^>nul') do set "_CALLER=%%N"

set "INLINE=0"
if /i "%_CALLER%"=="pwsh" set "INLINE=1"
if /i "%_CALLER%"=="powershell" set "INLINE=1"

if "%INLINE%"=="1" goto :run_inline

set "PS=powershell"
where pwsh >nul 2>&1
if %errorlevel%==0 set "PS=pwsh"
if exist "%LOCAL_PWSH%" set "PS=%LOCAL_PWSH%"

echo [INFO] Starte Codex CLI - Short Context
echo [INFO] Modus:   Neues Fenster
echo [INFO] Workdir: %WORKDIR%
echo [INFO] Context: %CONTEXT_WINDOW%, Auto-Compact: %AUTO_COMPACT%

start "Codex CLI [short]" "%PS%" -NoExit -Command ^
  "$env:LANG='en_US.UTF-8'; $env:LC_ALL='en_US.UTF-8'; $env:LESSCHARSET='utf-8'; $env:PYTHONUTF8='1'; Set-Location -LiteralPath '%WORKDIR%'; Write-Host ''; Write-Host ' Codex CLI - Short Context' -ForegroundColor Cyan; Write-Host ''; & '%CODEX_EXE%' -c model_context_window=%CONTEXT_WINDOW% -c model_auto_compact_token_limit=%AUTO_COMPACT% -C '%WORKDIR%'"

endlocal
exit /b 0

:run_inline
echo [INFO] Starte Codex CLI - Short Context
echo [INFO] Modus:   Inline
echo [INFO] Workdir: %WORKDIR%
echo [INFO] Context: %CONTEXT_WINDOW%, Auto-Compact: %AUTO_COMPACT%
cd /d "%WORKDIR%"
"%CODEX_EXE%" -c model_context_window=%CONTEXT_WINDOW% -c model_auto_compact_token_limit=%AUTO_COMPACT% -C "%WORKDIR%"
endlocal
exit /b 0

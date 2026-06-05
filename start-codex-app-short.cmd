@echo off
setlocal

rem Start Codex Desktop App in this project with the normal short context.
chcp 65001 >nul 2>&1

for %%I in ("%~dp0.") do set "WORKDIR=%%~fI"
set "CONTEXT_WINDOW=272000"
set "AUTO_COMPACT=240000"
set "CODEX_EXE=%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe"
set "WORKDIR_FWD=%WORKDIR:\=/%"
if "%WORKDIR_FWD:~-1%"=="/" set "WORKDIR_FWD=%WORKDIR_FWD:~0,-1%"
set "MCP_PYTHON=%WORKDIR_FWD%/.venv/Scripts/python.exe"
set "MCP_COMMAND_CONFIG=mcp_servers.agentkit3-concepts.command=\"%MCP_PYTHON%\""
set "MCP_ARGS_CONFIG=mcp_servers.agentkit3-concepts.args=[\"-m\",\"tools.concept_mcp.server\"]"
set "MCP_CWD_CONFIG=mcp_servers.agentkit3-concepts.cwd=\"%WORKDIR_FWD%\""

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
echo [INFO] MCP:     agentkit3-concepts

start "Codex App [short]" "%CODEX_EXE%" -c "%MCP_COMMAND_CONFIG%" -c "%MCP_ARGS_CONFIG%" -c "%MCP_CWD_CONFIG%" -c model_context_window=%CONTEXT_WINDOW% -c model_auto_compact_token_limit=%AUTO_COMPACT% app "%WORKDIR%"

endlocal
exit /b 0

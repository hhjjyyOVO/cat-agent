$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (!(Test-Path .env)) {
  Copy-Item .env.example .env
}

if (!(Test-Path .venv)) {
  python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py

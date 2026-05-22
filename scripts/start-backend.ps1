Set-Location $PSScriptRoot\..\backend

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

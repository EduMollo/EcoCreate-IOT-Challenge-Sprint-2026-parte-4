param([ValidateSet('auto','template','gemini','ollama','claude')][string]$Provider='auto')
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv\Scripts\python.exe')) { py -3.12 -m venv .venv; if($LASTEXITCODE -ne 0){throw 'Instale Python 3.12 para continuar.'} }
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install -r requirements.txt
if($LASTEXITCODE -ne 0){throw 'Falha ao instalar dependências.'}
& $python -m ai_core.risk_model train
if($LASTEXITCODE -ne 0){throw 'Falha no treinamento.'}
& $python -m unittest discover -s tests -v
if($LASTEXITCODE -ne 0){throw 'Falha nos testes.'}
if (!(Test-Path '.env')) {Copy-Item '.env.example' '.env'}
# Reuse the token in .env across restarts; never print it.
$tokenLine=Get-Content '.env' | Where-Object {$_ -match '^COPILOT_API_TOKEN=.+$'} | Select-Object -First 1
if (!$tokenLine) {
    $bytes=New-Object byte[] 32
    $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
    try {$rng.GetBytes($bytes)} finally {$rng.Dispose()}
    $secret=[BitConverter]::ToString($bytes).Replace('-','')
    (Get-Content '.env') -replace '^COPILOT_API_TOKEN=.*$',"COPILOT_API_TOKEN=$secret" | Set-Content -Encoding utf8 '.env'
}
$env:CLYVO_LLM_PROVIDER=$Provider
Write-Host 'Copilot em http://127.0.0.1:5001. Configure o Java com a URL e o mesmo token privado de .env.'
& $python app.py

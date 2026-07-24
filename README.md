cd C:\Marcio\Projetos\Totvs-IDeIA\Projetos\bot-carol-tezk42-contabil-runtime

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium

python -m agent.worker --dry-run --json
python -m agent.worker
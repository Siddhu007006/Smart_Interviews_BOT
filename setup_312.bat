@echo off
cd /d d:\bot
d:\bot\venv_312\Scripts\python.exe -m pip install -r requirements.txt
d:\bot\venv_312\Scripts\python.exe -m playwright install
d:\bot\venv_312\Scripts\python.exe --version

# Dabao Singapore
This repository contains code used to automate workflows for Dabao Singapore.

## Get started
1. Install `uv` and `playwright`.
```bash
chmod +x ./install-uv-playwright.sh
./install-uv-playwright.sh
```
2. Create virtual environment `dabaosg-venv` and install packages.
```bash
uv venv dabaosg-venv
source dabaosg-venv/bin/activate
uv pip install -r requirements.txt
```
3. Run script.
```python
python scrape_americatogo.py
```
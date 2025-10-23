# Dabao Singapore
This repository contains code used to automate workflows for Dabao Singapore.

## Get started
1. Clone this repository and change directory into it.
```bash
git clone https://github.com/jayellho/dabao-sg.git
cd dabao-sg
```
2. Install `uv` and `playwright`.
```bash
chmod +x ./install-uv-playwright.sh
./install-uv-playwright.sh
```
3. Create and activate virtual environment `dabaosg-venv` and install packages.
```bash
uv venv dabaosg-venv
source dabaosg-venv/bin/activate
uv pip install -r requirements.txt
```
4. Run script.
```python
python scrape_americatogo.py
```
5. Start the frontend.
NOTE: This was bootstrapped with Next.js using `pnpm create next-app@latest client`
```python
pnpm dev
```
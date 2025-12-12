# Dabao Singapore
This repository contains code used to automate workflows for Dabao Singapore.

## Get started
1. Clone this repository and change directory into it.
```bash
git clone https://github.com/jayellho/dabao-sg.git
cd dabao-sg
```
> **_NOTE:_** You would have to copy in the following credential files as provided to you as these are not pushed into GitHub: `.env`, `credentials.json` and `token.json`.

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

### EZCater
> **_NOTE:_** My understanding is that EZCater allows subscriptions to some events. It will emit events (e.g. new orders) to a subscribed webhook URL that is maintained by us.
0. [One-Time] Set-up a subscription to the events emitted by the EZCater GraphQL endpoint.
```python
python setup_ezcater_webhooks.py https://your-domain.com/webhook/ezcater
```

1. Run the webhook server.
```python
python simple_ezcater_webhook.py
```

2. [Testing] Edit the URL as needed then run this in a terminal to send a fake event to your webhook URL. Check Google calendar for the event.
```bash
curl -X POST http://127.0.0.1:5000/webhook/ezcater   -H "Content-Type: application/json"   -d '{
    "entity_type": "Order",
    "entity_id": "11111111-2222-3333-4444-555555555555",
    "key": "submitted",
    "occurred_at": "2025-12-11T18:00:00Z",
    "created_at": "2025-12-11T18:00:01Z"
  }'
```

3. Check health.
```bash
curl http://127.0.0.1:5000/health
```
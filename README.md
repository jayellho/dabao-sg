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
0. [One-Time] Set-up a subscription for your webhook URL to the events emitted by the EZCater GraphQL endpoint.
```python
python setup_ezcater_webhooks.py https://your-webhook-url/webhook/ezcater
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

## AWS Notes
> **_NOTE:_** The lightweight webhook server is currently hosted on an AWS EC2 instance.
### Connecting to the instance from a terminal
1. Get the private key `dabao-sg.pem`and `cd` into the directory where the private key is saved.
2. Run the following commands to connect via SSH:
```curl
chmod 400 dabao-sg.pem
ssh -i "dabao-sg.pem" ubuntu@ec2-18-188-170-191.us-east-2.compute.amazonaws.com
```

### Starting the webhook server in detached mode
0. [First Time] Install `screen` then create `screen` session called `dabao-sg`
```curl
sudo apt-get install screen
screen -S dabao-sg
```
1. Start existing session called `dabao-sg`:
```curl
screen -r dabao-sg
```
2. Exit current active session with `Ctrl+A` then `D`. Always do this before exiting the SSH connection to keep the webhook server running.
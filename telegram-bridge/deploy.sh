#!/bin/bash
set -e

PI="user@your-pi.local"
REMOTE_DIR="/home/YOUR_USER/whatsapp-scheduler/telegram-bridge"

echo "Syncing files to host..."
rsync -avz --exclude 'venv' --exclude '__pycache__' --exclude '.env' \
  ./ "$PI:$REMOTE_DIR/"

echo "Setting up on host..."
ssh "$PI" << 'EOF'
cd ~/whatsapp-scheduler/telegram-bridge

# Create virtualenv and install deps
python3 -m venv venv 2>/dev/null || true
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

# Init contacts file if not present
[ -f ~/whatsapp-scheduler/contacts.json ] || echo '{}' > ~/whatsapp-scheduler/contacts.json
echo "contacts.json ready at ~/whatsapp-scheduler/contacts.json"

# Sudoers rule for passwordless scheduler restart (replace YOUR_USER)
SUDOERS_LINE="YOUR_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart whatsapp-scheduler.service, /usr/bin/systemctl stop whatsapp-scheduler.service"
if ! sudo grep -qF "whatsapp-scheduler.service" /etc/sudoers.d/whatsapp-scheduler 2>/dev/null; then
  echo "$SUDOERS_LINE" | sudo tee /etc/sudoers.d/whatsapp-scheduler > /dev/null
  sudo chmod 0440 /etc/sudoers.d/whatsapp-scheduler
  echo "sudoers rule installed"
else
  echo "sudoers rule already present"
fi

# Install and start systemd service
sudo cp whatsapp-telegram-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now whatsapp-telegram-bridge.service

echo ""
echo "Deployed! Bot status:"
sudo systemctl status whatsapp-telegram-bridge.service --no-pager -l
EOF

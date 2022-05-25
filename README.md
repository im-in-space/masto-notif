# Masto-Notif
> Notifications with Discord webhooks for admins


```bash
# Install deps
pip install -r requirements.txt

# Copy the base config file
cp config.py.dist config.py

# Edit it with your infos
$EDITOR config.py

# Run
python newRegs.py
python newTrends.py

# Add a cron like
# */10 * * * * cd ~/masto-notif && bash -c 'date ; python newRegs.py ; python newTrends.py' > cron.log 2>&1
```

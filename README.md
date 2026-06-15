# Masto-Notif
> Notifications with Discord webhooks for admins


```bash
# Install deps
# -- using uv
uv sync --managed-python
# -- or plain pip
pip install -U .

# Copy the base config file
cp config.py.dist config.py

# Edit it with your infos
$EDITOR config.py

# Run
# -- using uv
uv run newRegs.py
uv run newTrends.py
# -- or plain python
python newRegs.py
python newTrends.py

# Add a cron like
# */10 * * * * cd ~/masto-notif && bash -c 'date ; uv run newRegs.py ; uv run newTrends.py' > cron.log 2>&1
```

### Important note

This code is provided as-is and without intention of providing additional help.  
There may be unannounced broken changes and no support will be provided.

Three external services are used in [`newRegs.py`](newRegs.py):

- [Stop Forum Spam](https://www.stopforumspam.com/) is used to check if an IP or email is in their database.
- [Verifier](https://verifier.meetchopra.com/) is used to check if a domain is valid and not used for disposable addresses, you'll need to signup to get a (free) API key.
- [SkipSend](https://skipsend.com/api-docs/) to also check for disposable addresses, no API key needed here.

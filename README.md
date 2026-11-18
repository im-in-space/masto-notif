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
- [SkipSend](https://skipsend.com/api-docs/) to check for disposable addresses.
- [FakeFilter](https://fakefilter.net/static/docs/restful/) to check for disposable domains.
- [Team Cymru](https://www.team-cymru.com/ip-asn-mapping) for the ASN, network name and (fallback) country.
- DNS Blocklists: Spamhaus ZEN (with IPv6 support), SpamCop, UCEPROTECT (level 1), DroneBL and EFnet RBL.

Optionally, set `maxmind_db` in the config to a [GeoLite2 Country database](https://www.maxmind.com/en/geolite2/signup) for a better GeoIP.

> [!NOTE]
> Spamhaus refuses queries coming from public resolvers (Google, Cloudflare, ...) and heavy volumes.
> Use your own/ISP resolver, or the lookup will be reported as "query refused".

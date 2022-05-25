import os
import time
import datetime
import requests
import config as cfg

from discord_webhook import DiscordWebhook, DiscordEmbed

if os.path.exists('reg_last.txt'):
    with open('reg_last.txt', "r") as f:
        last_id = f.read()
else:
    last_id = ''

headers = {
    "Authorization": "Bearer " + cfg.token
}

response = requests.request(
    "GET",
    cfg.base_url + "/api/v1/admin/accounts",
    headers=headers,
    params={
        "local": "true"
    }
)

first_id = None

for u in response.json():
    if u['id'] == last_id:
        break

    if not u['confirmed']:
        continue

    if first_id is None:
        first_id = u['id']

    webhook = DiscordWebhook(
        url=cfg.whook,
        rate_limit_retry=True
    )

    embed = DiscordEmbed(
        title='New registration',
        url=cfg.base_url + '/admin/accounts/' + u['id'],
        color='03b2f8'
    )

    if "missing.png" not in u['account']['avatar']:
        embed.set_thumbnail(url=u['account']['avatar'])

    try:
        ts = datetime.datetime.strptime(
            u['created_at'], "%Y-%m-%dT%H:%M:%S.%f%z"
        ).timestamp()
        embed.set_timestamp(timestamp=ts)
    except Exception:
        # Silently ignore
        print('Timestamp fail')
        pass

    embed.add_embed_field(name='Username', value=u['username'])
    embed.add_embed_field(name='Email', value=u['email'], inline=False)
    embed.add_embed_field(name='Locale', value=u['locale'])
    embed.add_embed_field(name='Last IP', value=u['ip']['ip'])

    webhook.add_embed(embed)
    response = webhook.execute()

    time.sleep(2)

if first_id is not None:
    last_id = first_id

with open('reg_last.txt', "w") as f:
    f.write(last_id)

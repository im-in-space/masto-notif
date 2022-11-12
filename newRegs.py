import os
import time
import sqlite3
import datetime
import requests
import config as cfg

from shutil import copyfile
from discord_webhook import DiscordWebhook, DiscordEmbed

# Ready the SQLite DB
try:
    # If there's no database file, copy from the empty one
    if not os.path.isfile('db.sqlite'):
        copyfile('empty.sqlite', 'db.sqlite')

    # Connect to SQLite3 DB
    db = sqlite3.connect('db.sqlite')
    cur = db.cursor()
except Exception as e:
    print("Error while trying to load DB: " + str(e))
    exit(1)

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

for u in response.json():
    r = cur.execute(
        'SELECT COUNT(userid) FROM knownRegs WHERE userid=?',
        (u['id'],)
    ).fetchone()
    if r[0] != 0:
        continue

    if not u['confirmed']:
        continue

    print(u)

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
    embed.add_embed_field(name='Locale', value=u['locale'])
    embed.add_embed_field(name='Email', value=u['email'], inline=False)

    # Spam check
    try:
        sr = requests.post(
            'http://api.stopforumspam.org/api?json',
            data={
                'email': u['email'],
                'ip': u['ip']
            }
        )
        sc = sr.json()

        sce = 'OK'
        if sc['email']['appears'] == 1:
            sce = 'Freq.: {}, Seen: {}, Confidence: {}'.format(
                sc['email']['frequency'],
                sc['email']['lastseen'],
                sc['email']['confidence']
            )

        embed.add_embed_field(name='Email Check', value=sce, inline=False)

        sci = 'OK'
        if sc['ip']['appears'] == 1:
            sci = 'Country: {}, Freq.: {}, Seen: {}, Confidence: {}'.format(
                sc['ip']['country'],
                sc['ip']['frequency'],
                sc['ip']['lastseen'],
                sc['ip']['confidence']
            )

        embed.add_embed_field(name='IP Check', value=sci, inline=False)
    except requests.exceptions.RequestException as e:
        print('StopForumSpam request failed. ' + str(e))
    except Exception as e:
        print('StopForumSpam check failed. ' + str(e))

    webhook.add_embed(embed)
    response = webhook.execute()

    cur.execute(
        'INSERT INTO knownRegs(userid) VALUES (?)',
        (u['id'],)
    )

    time.sleep(2)

db.commit()
db.close()

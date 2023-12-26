import os
import time
import sqlite3
import datetime
import requests
import config as cfg

from shutil import copyfile
from verifier import verifier
from discord_webhook import DiscordWebhook, DiscordEmbed


def _debug(msg, obj=''):
    if (cfg.DEBUG_MODE):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        print('[' + now + '] ' + msg, obj)


# Ready the SQLite DB
try:
    # If there's no database file, copy from the empty one
    if not os.path.isfile('db.sqlite'):
        _debug('DB copied from empty')
        copyfile('empty.sqlite', 'db.sqlite')

    # Connect to SQLite3 DB
    _debug('Connecting to DB...')
    db = sqlite3.connect('db.sqlite')
    _debug('Done')
    _debug('Getting cursor...')
    cur = db.cursor()
    _debug('Done')
except Exception as e:
    print("Error while trying to load DB: " + str(e))
    exit(1)

headers = {
    "Authorization": "Bearer " + cfg.token
}

_debug('Requesting local accounts...')
response = requests.request(
    "GET",
    cfg.base_url + "/api/v1/admin/accounts",
    headers=headers,
    params={
        "local": "true"
    }
)
_debug('Done.')

for u in response.json():
    _debug('Parsing user: ', u)
    ping_admin = False

    r = cur.execute(
        'SELECT COUNT(userid) FROM knownRegs WHERE userid=?',
        (u['id'],)
    ).fetchone()
    if r[0] != 0:
        _debug('User already done')
        continue

    _debug('New user, making webhook')
#    if not u['confirmed']:
#        continue

#    print(u)

    webhook = DiscordWebhook(
        url=cfg.whook_reg,
        rate_limit_retry=True
    )

    embed = DiscordEmbed(
        title='New registration',
        url=cfg.base_url + '/admin/accounts/' + u['id'],
        color='03b2f8'
    )

    if "missing.png" not in u['account']['avatar']:
        _debug('They have an avatar!')
        embed.set_thumbnail(url=u['account']['avatar'])

    try:
        ts = datetime.datetime.strptime(
            u['created_at'], "%Y-%m-%dT%H:%M:%S.%f%z"
        ).timestamp()
        embed.set_timestamp(timestamp=ts)
        _debug('Timestamp added')
    except Exception:
        # Silently ignore
        print('Timestamp fail')
        pass

    embed.add_embed_field(name='Username', value=u['username'])
    embed.add_embed_field(name='Locale', value=u['locale'])
    embed.add_embed_field(name='Email', value=u['email'], inline=False)

    # Spam check
    try:
        _debug('Checking spam...')
        sr = requests.post(
            'http://api.stopforumspam.org/api?json',
            data={
                'email': u['email'],
                'ip': u['ip']
            }
        )
        sc = sr.json()
        _debug('Done and JSON got', sc)

        sce = 'OK'
        if sc['email']['appears'] == 1:
            _debug('Email found in spam')
            ping_admin = True
            sce = 'Freq.: {}, Seen: {}, Confidence: {}'.format(
                sc['email']['frequency'],
                sc['email']['lastseen'],
                sc['email']['confidence']
            )

        embed.add_embed_field(
            name='Email Check',
            value=sce,
            inline=False
        )

        sci = 'OK'
        if sc['ip']['appears'] == 1:
            _debug('IP found in spam')
            ping_admin = True
            sci = 'Country: {}, Freq.: {}, Seen: {}, Confidence: {}'.format(
                sc['ip']['country'],
                sc['ip']['frequency'],
                sc['ip']['lastseen'],
                sc['ip']['confidence']
            )

        embed.add_embed_field(
            name='IP Check',
            value=sci,
            inline=False
        )
        _debug('Spam check embed added')
    except requests.exceptions.RequestException as e:
        print('StopForumSpam request failed. ' + str(e))
    except Exception as e:
        print('StopForumSpam check failed. ' + str(e))

    # Check for Burner Email Providers
    try:
        if cfg.verifier_key:
            _debug('Checking burner')
            bi = 'OK'
            if not verifier.verify(u['email'], cfg.verifier_key):
                _debug('Email is a burner')
                ping_admin = True
                bi = 'DID NOT PASS'

            embed.add_embed_field(
                name='Burner Email Check',
                value=bi,
                inline=False
            )
            _debug('Burner check embed added')
    except Exception as e:
        print('Disposable Email Detector check failed. ' + str(e))

    webhook.add_embed(embed)

    if ping_admin and cfg.discord_uid:
        _debug('Will ping admin')
        webhook.content = f'<@{cfg.discord_uid}>'

    _debug('Sending webhook...')
    response = webhook.execute()
    _debug('Done', response)

    _debug('Inserting to table...')
    cur.execute(
        'INSERT INTO knownRegs(userid) VALUES (?)',
        (u['id'],)
    )
    _debug('Done')

    time.sleep(2)

_debug('Commit DB...')
db.commit()
_debug('Done')
_debug('Closing DB...')
db.close()
_debug('Done')

import os
import time
import sqlite3
import datetime
import requests
import html2text
import config as cfg

from shutil import copyfile
from discord_webhook import DiscordWebhook, DiscordEmbed


def _debug(msg, obj=''):
    if (cfg.DEBUG_MODE):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        print('[' + now + '] ' + msg, obj)


db = None

_debug('Init html2text')
h = html2text.HTML2Text()
h.ignore_links = True
_debug('Done')

headers = {
    "Authorization": "Bearer " + cfg.token
}


def trends_statuses(admin=False):
    _debug('=> trends_statuses(' + str(admin) + ')')
    db_s = db.cursor()

    endpoint = "/api/v1/trends/statuses"
    if admin:
        endpoint = "/api/v1/admin/trends/statuses"

    _debug('Fetching ' + endpoint + '...')
    response = requests.request(
        "GET",
        cfg.base_url + endpoint,
        headers=headers
    )
    _debug('Done')

    for s in response.json():
        r = db_s.execute(
            'SELECT COUNT(postid) FROM knownTrendingPosts WHERE postid=?',
            (s['id'],)
        ).fetchone()
        if r[0] != 0:
            _debug(str(s['id']) + ' already done')
            continue

        _debug('Inserting ' + str(s['id']) + '...')
        db_s.execute(
            'INSERT INTO knownTrendingPosts(postid) VALUES (?)',
            (s['id'],)
        )
        _debug('Done')

        auto_approve = False

        if (admin and cfg.trends_auto and  # If this is running as the admin view and we enabled auto-trends
            s['requires_review'] and  # and if this trend is awaiting review
            not any(substring in s['content'] for substring in cfg.trends_hold)):  # and it doesn't contain "hold" terms
            try:
                # This endpoint was introduced in 4db8230 for Mastodon 4.1.3
                _debug('Auto-approving ' + str(s['id']) + '...')
                pr = requests.request(
                    "POST",
                    "{base}{endpoint}/{id}/approve".format(base=cfg.base_url, endpoint=endpoint, id=s['id']),
                    headers=headers
                )
                _debug('Done')

                if pr.status_code == requests.codes.ok:
                    auto_approve = True
                    print('Auto approved ' + str(s['id']))
            except Exception:
                # Silently ignore
                print('Auto approve failed')
                pass

        whook_url = cfg.whook_trends_ok
        if admin and not auto_approve:
            _debug('Will send to not auto-approved webhook')
            whook_url = cfg.whook_trends_rev

        webhook = DiscordWebhook(
            url=whook_url,
            rate_limit_retry=True
        )

        embed = DiscordEmbed(
            title='New trending status',
            url=cfg.base_url + '/admin/trends/statuses',
            description=h.handle(s['content'])[:500],
            color='02954a'
        )

        embed.set_author(
            name=s['account']['acct'],
            url=s['url'],
            icon_url=s['account']['avatar']
        )

        try:
            ts = datetime.datetime.strptime(
                s['created_at'], "%Y-%m-%dT%H:%M:%S.%f%z"
            ).timestamp()
            embed.set_timestamp(timestamp=ts)
        except Exception:
            # Silently ignore
            print('Timestamp fail')
            pass

        embed.add_embed_field(name='Replies', value=s['replies_count'])
        embed.add_embed_field(name='Boosts', value=s['reblogs_count'])
        embed.add_embed_field(name='Favorites', value=s['favourites_count'])

        if len(s['media_attachments']) > 0:
            _debug('There are file attachements')
            embed.add_embed_field(
                name='Attachments',
                value=str(len(s['media_attachments'])),
                inline=False
            )

            for m in s['media_attachments']:
                if m['type'] == 'image':
                    _debug('Adding an attachments since it is an image')
                    embed.set_image(url=m['preview_url'])
                    break  # Only one element

        webhook.add_embed(embed)
        _debug('Sending webhook...')
        response = webhook.execute()
        _debug('Done', response)

        time.sleep(2)


def trends_links(admin=False):
    _debug('=> trends_links(' + str(admin) + ')')
    db_l = db.cursor()

    endpoint = "/api/v1/trends/links"
    if admin:
        endpoint = "/api/v1/admin/trends/links"

    _debug('Fetching ' + endpoint + '...')
    response = requests.request(
        "GET",
        cfg.base_url + endpoint,
        headers=headers
    )
    _debug('Done')

    for link in response.json():
        r = db_l.execute(
            'SELECT COUNT(url) FROM knownTrendingLinks WHERE url=?',
            (link['url'],)
        ).fetchone()
        if r[0] != 0:
            _debug(str(link['url']) + ' already done')
            continue

        _debug('Inserting ' + str(link['url']) + '...')
        db_l.execute(
            'INSERT INTO knownTrendingLinks(url) VALUES (?)',
            (link['url'],)
        )
        _debug('Done')

        whook_url = cfg.whook_trends_ok
        if admin:
            _debug('Will send to not auto-approved webhook')
            whook_url = cfg.whook_trends_rev

        webhook = DiscordWebhook(
            url=whook_url,
            rate_limit_retry=True
        )

        embed = DiscordEmbed(
            title='New trending link',
            url=cfg.base_url + '/admin/trends/links',
            description='**' + link['title'] + '**\n\n' +
                        link['description'][:500],
            color='950202'
        )

        embed.set_timestamp()

        if link['provider_name'] != '':
            _debug('Adding provider name')
            embed.set_footer(text=link['provider_name'])

        if link['image'] != '':
            _debug('Adding image')
            embed.set_thumbnail(url=link['image'])

        webhook.add_embed(embed)
        _debug('Sending webhook...')
        response = webhook.execute()
        _debug('Done', response)

        time.sleep(2)


if __name__ == "__main__":
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
    except Exception as e:
        print("Error while trying to load DB: " + str(e))
        exit(1)

    trends_statuses(False)
    trends_statuses(True)

    trends_links(False)
    trends_links(True)

    _debug('Commit DB...')
    db.commit()
    _debug('Done')
    _debug('Closing DB...')
    db.close()
    _debug('Done')

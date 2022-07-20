import os
import time
import sqlite3
import datetime
import requests
import html2text
import config as cfg

from shutil import copyfile
from discord_webhook import DiscordWebhook, DiscordEmbed

db = None

h = html2text.HTML2Text()
h.ignore_links = True

headers = {
    "Authorization": "Bearer " + cfg.token
}


def trends_statuses():
    db_s = db.cursor()

    response = requests.request(
        "GET",
        cfg.base_url + "/api/v1/admin/trends/statuses",
        headers=headers
    )

    for s in response.json():
        r = db_s.execute(
            'SELECT COUNT(postid) FROM knownTrendingPosts WHERE postid=?',
            (s['id'],)
        ).fetchone()
        if r[0] != 0:
            continue

        db_s.execute(
            'INSERT INTO knownTrendingPosts(postid) VALUES (?)',
            (s['id'],)
        )

        webhook = DiscordWebhook(
            url=cfg.whook,
            rate_limit_retry=True
        )

        embed = DiscordEmbed(
            title='New trending status',
            url=cfg.base_url + '/admin/trends/statuses',
            description=h.handle(s['content'][:1500]),
            color='02954a'
        )

        embed.set_author(
            name=s['account']['acct'],
            url=s['account']['url'],
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
            embed.add_embed_field(
                name='Attachments',
                value=str(len(s['media_attachments'])),
                inline=False
            )

            for m in s['media_attachments']:
                if m['type'] == 'image':
                    embed.set_image(url=m['preview_url'])
                    break  # Only one element

        webhook.add_embed(embed)
        response = webhook.execute()

        time.sleep(2)


def trends_links():
    db_l = db.cursor()

    response = requests.request(
        "GET",
        cfg.base_url + "/api/v1/admin/trends/links",
        headers=headers
    )

    for link in response.json():
        r = db_l.execute(
            'SELECT COUNT(url) FROM knownTrendingLinks WHERE url=?',
            (link['url'],)
        ).fetchone()
        if r[0] != 0:
            continue

        db_l.execute(
            'INSERT INTO knownTrendingLinks(url) VALUES (?)',
            (link['url'],)
        )

        webhook = DiscordWebhook(
            url=cfg.whook,
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
            embed.set_footer(text=link['provider_name'])

        if link['image'] != '':
            embed.set_thumbnail(url=link['image'])

        webhook.add_embed(embed)
        response = webhook.execute()

        time.sleep(2)


if __name__ == "__main__":
    # Ready the SQLite DB
    try:
        # If there's no database file, copy from the empty one
        if not os.path.isfile('db.sqlite'):
            copyfile('empty.sqlite', 'db.sqlite')

        # Connect to SQLite3 DB
        db = sqlite3.connect('db.sqlite')
    except Exception as e:
        print("Error while trying to load DB: " + str(e))
        exit(1)

    trends_statuses()
    trends_links()

    db.commit()
    db.close()

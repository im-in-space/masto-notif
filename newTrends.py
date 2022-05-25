import json
import time
import datetime
import os
import requests
import html2text
import config as cfg

from discord_webhook import DiscordWebhook, DiscordEmbed

h = html2text.HTML2Text()
h.ignore_links = True

headers = {
    "Authorization": "Bearer " + cfg.token
}


def trends_statuses():
    if os.path.exists('trendsStatuses.json'):
        with open('trendsStatuses.json', "r") as f:
            statuses = json.load(f)
    else:
        statuses = []

    response = requests.request(
        "GET",
        cfg.base_url + "/api/v1/admin/trends/statuses",
        headers=headers
    )

    for s in response.json():
        if s['id'] in statuses:
            continue

        statuses.append(s['id'])

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

    with open('trendsStatuses.json', "w") as f:
        json.dump(statuses, f)


def trends_links():
    if os.path.exists('trendsLinks.json'):
        with open('trendsLinks.json', "r") as f:
            links = json.load(f)
    else:
        links = []

    response = requests.request(
        "GET",
        cfg.base_url + "/api/v1/admin/trends/links",
        headers=headers
    )

    for link in response.json():
        if link['url'] in links:
            continue

        links.append(link['url'])

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

    with open('trendsLinks.json', "w") as f:
        json.dump(links, f)


trends_statuses()
trends_links()

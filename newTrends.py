import datetime
import sqlite3
import sys
import time
from pathlib import Path
from shutil import copyfile

import html2text
import requests
from discord_webhook import DiscordEmbed, DiscordWebhook

import config as cfg


def _debug(msg: str, obj: object = "") -> None:
    """Print a timestamped debug message when DEBUG_MODE is enabled.

    Args:
        msg: The message text to print.
        obj: An optional value to append after the message.
    """
    if cfg.DEBUG_MODE:
        now = datetime.datetime.now(tz=datetime.UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
        print("[" + now + "] " + msg, obj)


def _try_auto_approve_status(s: dict, endpoint: str) -> bool:
    """Attempt to auto-approve a trending status via the Mastodon admin API.

    Only makes the approval request when ``cfg.trends_auto`` is enabled, the
    status is awaiting review, and its content contains none of the hold
    keywords defined in ``cfg.trends_hold``.

    Args:
        s: Mastodon status object from the trends API response.
        endpoint: API endpoint path used to fetch the trend (used to build
            the approval URL).

    Returns:
        True if the status was successfully approved, False otherwise.
    """
    if not (cfg.trends_auto and s["requires_review"] and not any(substring in s["content"] for substring in cfg.trends_hold)):
        return False
    auto_approve = False
    try:
        # This endpoint was introduced in 4db8230 for Mastodon 4.1.3
        _debug("Auto-approving " + str(s["id"]) + "...")
        pr = requests.request(
            "POST",
            "{base}{endpoint}/{id}/approve".format(base=cfg.base_url, endpoint=endpoint, id=s["id"]),
            headers={"Authorization": "Bearer " + cfg.token},
            timeout=30,
        )
        _debug("Done")
        if pr.status_code == requests.codes.ok:
            auto_approve = True
            print("Auto approved " + str(s["id"]))
    except Exception:
        # Silently ignore
        print("Auto approve failed")
    return auto_approve


def _send_status_webhook(s: dict, whook_url: str) -> None:
    """Build and dispatch a Discord webhook embed for a trending status.

    Creates an embed containing the status content (HTML stripped), author
    info, engagement counts, and the first image attachment if present, then
    sends it to ``whook_url``.

    Args:
        s: Mastodon status object from the trends API response.
        whook_url: Discord webhook URL to post the embed to.
    """
    webhook = DiscordWebhook(url=whook_url, rate_limit_retry=True)

    h = html2text.HTML2Text()
    h.ignore_links = True

    embed = DiscordEmbed(
        title="New trending status",
        url=cfg.base_url + "/admin/trends/statuses",
        description=h.handle(s["content"])[:500],
        color="02954a",
    )

    embed.set_author(name=s["account"]["acct"], url=s["url"], icon_url=s["account"]["avatar"])

    try:
        ts = datetime.datetime.strptime(s["created_at"], "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
        embed.set_timestamp(timestamp=ts)
    except Exception:
        # Silently ignore
        print("Timestamp fail")

    embed.add_embed_field(name="Replies", value=s["replies_count"])
    embed.add_embed_field(name="Boosts", value=s["reblogs_count"])
    embed.add_embed_field(name="Favorites", value=s["favourites_count"])

    if len(s["media_attachments"]) > 0:
        _debug("There are file attachements")
        embed.add_embed_field(name="Attachments", value=str(len(s["media_attachments"])), inline=False)

        for m in s["media_attachments"]:
            if m["type"] == "image":
                _debug("Adding an attachments since it is an image")
                embed.set_image(url=m["preview_url"])
                break  # Only one element

    webhook.add_embed(embed)

    if cfg.DRY_RUN:
        print("DRY_RUN set, skipping webhook execution")
    else:
        _debug("Sending webhook...")
        response = webhook.execute()
        _debug("Done", response)

        time.sleep(2)


def trends_statuses(db, *, admin: bool = False) -> None:
    """Fetch trending statuses and notify Discord for new entries.

    1. Queries either the public or admin trending-statuses endpoint
    2. Records each new status in the local database
    3. Optionally auto-approves it via the Mastodon API
    4. Sends a Discord webhook, if needed

    Args:
        admin: When True, use the admin API endpoint and apply auto-approval
            logic. Defaults to False.
    """
    _debug("=> trends_statuses(" + str(admin) + ")")

    if db is None:
        msg = "Database connection is not initialized"
        raise RuntimeError(msg)
    db_s = db.cursor()

    endpoint = "/api/v1/trends/statuses"
    if admin:
        endpoint = "/api/v1/admin/trends/statuses"

    _debug("Fetching " + endpoint + "...")
    response = requests.request("GET", cfg.base_url + endpoint, headers={"Authorization": "Bearer " + cfg.token}, timeout=30)
    _debug("Done")

    for s in response.json():
        r = db_s.execute("SELECT COUNT(postid) FROM knownTrendingPosts WHERE postid=?", (s["id"],)).fetchone()
        if r[0] != 0:
            _debug(str(s["id"]) + " already done")
            continue

        _debug("Inserting " + str(s["id"]) + "...")
        db_s.execute("INSERT INTO knownTrendingPosts(postid) VALUES (?)", (s["id"],))
        _debug("Done")

        auto_approve = _try_auto_approve_status(s, endpoint) if admin else False

        whook_url = cfg.whook_trends_ok
        if admin and not auto_approve:
            _debug("Will send to not auto-approved webhook")
            whook_url = cfg.whook_trends_rev
        elif not cfg.whook_trends_ok_enable:
            continue

        _debug("Sending webhook...")
        _send_status_webhook(s, whook_url)


def trends_links(db, *, admin: bool = False) -> None:
    """Fetch trending links and notify Discord for new entries.

    1. Queries either the public or admin trending-links endpoint
    2. Records each new link in the local database
    3. Sends a Discord webhook, if needed

    Args:
        admin: When True, use the admin API endpoint. Defaults to False.
    """
    _debug("=> trends_links(" + str(admin) + ")")

    if db is None:
        msg = "Database connection is not initialized"
        raise RuntimeError(msg)
    db_l = db.cursor()

    endpoint = "/api/v1/trends/links"
    if admin:
        endpoint = "/api/v1/admin/trends/links"

    _debug("Fetching " + endpoint + "...")
    response = requests.request("GET", cfg.base_url + endpoint, headers={"Authorization": "Bearer " + cfg.token}, timeout=30)
    _debug("Done")

    for link in response.json():
        r = db_l.execute("SELECT COUNT(url) FROM knownTrendingLinks WHERE url=?", (link["url"],)).fetchone()
        if r[0] != 0:
            _debug(str(link["url"]) + " already done")
            continue

        _debug("Inserting " + str(link["url"]) + "...")
        db_l.execute("INSERT INTO knownTrendingLinks(url) VALUES (?)", (link["url"],))
        _debug("Done")

        whook_url = cfg.whook_trends_ok
        if admin:
            _debug("Will send to not auto-approved webhook")
            whook_url = cfg.whook_trends_rev
        elif not cfg.whook_trends_ok_enable:
            continue

        webhook = DiscordWebhook(url=whook_url, rate_limit_retry=True)

        embed = DiscordEmbed(
            title="New trending link",
            url=cfg.base_url + "/admin/trends/links",
            description="**" + link["title"] + "**\n\n" + link["description"][:500],
            color="950202",
        )

        embed.set_timestamp()

        if link["provider_name"] != "":
            _debug("Adding provider name")
            embed.set_footer(text=link["provider_name"])

        if link["image"] != "":
            _debug("Adding image")
            embed.set_thumbnail(url=link["image"])

        webhook.add_embed(embed)

        if cfg.DRY_RUN:
            print("DRY_RUN set, skipping webhook execution")
        else:
            _debug("Sending webhook...")
            response = webhook.execute()
            _debug("Done", response)

            time.sleep(2)


if __name__ == "__main__":
    # Ready the SQLite DB
    try:
        # If there's no database file, copy from the empty one
        if not Path("db.sqlite").is_file():
            _debug("DB copied from empty")
            copyfile("empty.sqlite", "db.sqlite")

        # Connect to SQLite3 DB
        _debug("Connecting to DB...")
        db = sqlite3.connect("db.sqlite")
        _debug("Done")
    except Exception as e:
        print("Error while trying to load DB: " + str(e))
        sys.exit(1)

    trends_statuses(db, admin=False)
    trends_statuses(db, admin=True)

    trends_links(db, admin=False)
    trends_links(db, admin=True)

    _debug("Commit DB...")
    db.commit()
    _debug("Done")
    _debug("Closing DB...")
    db.close()
    _debug("Done")

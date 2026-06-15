import datetime
import sqlite3
import sys
import time
from pathlib import Path
from shutil import copyfile

import requests
from discord_webhook import DiscordEmbed, DiscordWebhook
from verifier import verifier

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


def _check_spam(u: dict, embed: DiscordEmbed) -> bool:
    """Check email and IP against StopForumSpam, adding results to the embed.

    Args:
        u: Mastodon account object containing email and ip fields.
        embed: Discord embed to append Email Check and IP Check fields to.

    Returns:
        True if either the email or IP was found in the spam database.
    """
    result = False
    try:
        _debug("Checking spam...")
        sr = requests.post("http://api.stopforumspam.org/api?json", data={"email": u["email"], "ip": u["ip"]}, timeout=30)
        sc = sr.json()
        _debug("Done and JSON got", sc)

        sce = "OK"
        if sc["email"]["appears"] == 1:
            _debug("Email found in spam")
            result = True
            sce = "Freq.: {}, Seen: {}, Confidence: {}".format(sc["email"]["frequency"], sc["email"]["lastseen"], sc["email"]["confidence"])

        embed.add_embed_field(name="Email Check", value=sce, inline=False)

        sci = "OK"
        if sc["ip"]["appears"] == 1:
            _debug("IP found in spam")
            result = True
            sci = "Country: {}, Freq.: {}, Seen: {}, Confidence: {}".format(
                sc["ip"]["country"],
                sc["ip"]["frequency"],
                sc["ip"]["lastseen"],
                sc["ip"]["confidence"],
            )

        embed.add_embed_field(name="IP Check", value=sci, inline=False)
        _debug("Spam check embed added")
    except requests.exceptions.RequestException as e:
        print("StopForumSpam request failed. " + str(e))
    except Exception as e:
        print("StopForumSpam check failed. " + str(e))

    return result


def _check_verifier(u: dict, embed: DiscordEmbed) -> bool:
    """Check if the email is from a disposable provider, adding the result to the embed.

    Skips the check entirely when ``cfg.verifier_key`` is not configured.

    Args:
        u: Mastodon account object containing the email field.
        embed: Discord embed to append the Verifier Email Check field to.

    Returns:
        True if the email did not pass the disposable-email check.
    """
    if not cfg.verifier_key:
        return False

    result = False
    try:
        _debug("Checking with verifier")
        bi = "OK"
        if not verifier.verify(u["email"], cfg.verifier_key):
            _debug("Email is a burner")
            result = True
            bi = "DID NOT PASS"

        embed.add_embed_field(name="Verifier Email Check", value=bi, inline=False)
        _debug("Verifier check embed added")
    except Exception as e:
        print("Verifier check failed. " + str(e))

    return result


def process_user(db: sqlite3.Connection, u: dict) -> None:
    """Send a Discord notification for a newly registered user.

    1. Skips users already recorded in the database.
    2. Checks email and IP against:
        - StopForumSpam
        - verifier.meetchopra.com
    3. Posts a summary embed to the configured Discord webhook
    4. Records the user in the database

    Args:
        u: Mastodon account object from the admin accounts API response.
    """
    _debug("=> process_user")

    if db is None:
        msg = "Database connection is not initialized"
        raise RuntimeError(msg)
    cur = db.cursor()

    r = cur.execute("SELECT COUNT(userid) FROM knownRegs WHERE userid=?", (u["id"],)).fetchone()
    if r[0] != 0:
        _debug("User already done")
        return

    _debug("New user, making webhook")

    webhook = DiscordWebhook(url=cfg.whook_reg, rate_limit_retry=True)
    embed = DiscordEmbed(title="New registration", url=cfg.base_url + "/admin/accounts/" + u["id"], color="03b2f8")

    if "missing.png" not in u["account"]["avatar"]:
        _debug("They have an avatar!")
        embed.set_thumbnail(url=u["account"]["avatar"])

    try:
        ts = datetime.datetime.strptime(u["created_at"], "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
        embed.set_timestamp(timestamp=ts)
        _debug("Timestamp added")
    except Exception:
        # Silently ignore
        print("Timestamp fail")

    embed.add_embed_field(name="Username", value=u["username"])
    embed.add_embed_field(name="Locale", value=u["locale"])
    embed.add_embed_field(name="Email", value=u["email"], inline=False)

    if cfg.DRY_RUN:
        print("DRY_RUN set, not checking user")
        spam_flagged = False
        verifier_flagged = False
    else:
        spam_flagged = _check_spam(u, embed)
        verifier_flagged = _check_verifier(u, embed)

    ping_admin = spam_flagged or verifier_flagged

    webhook.add_embed(embed)

    if ping_admin and cfg.discord_uid:
        _debug("Will ping admin")
        webhook.content = f"<@{cfg.discord_uid}>"

    if cfg.DRY_RUN:
        print("DRY_RUN set, skipping webhook execution")
    else:
        _debug("Sending webhook...")
        response = webhook.execute()
        _debug("Done", response)

    _debug("Inserting to table...")
    cur.execute("INSERT INTO knownRegs(userid) VALUES (?)", (u["id"],))
    _debug("Done")

    if not cfg.DRY_RUN:
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

    _debug("Requesting local accounts...")
    response = requests.request(
        "GET",
        cfg.base_url + "/api/v1/admin/accounts",
        headers={"Authorization": "Bearer " + cfg.token},
        params={"local": "true"},
        timeout=30,
    )
    _debug("Done.")

    for u in response.json():
        _debug("Parsing user: ", u)
        process_user(db, u)

    _debug("Commit DB...")
    db.commit()
    _debug("Done")

    _debug("Closing DB...")
    db.close()
    _debug("Done")

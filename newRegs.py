import datetime
import sqlite3
import sys
import time
from pathlib import Path
from shutil import copyfile

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


def _check_skipsend(u: dict, embed: DiscordEmbed) -> bool:
    """Check email against SkipSend, adding results to the embed.

    Args:
        u: Mastodon account object containing the email field.
        embed: Discord embed to append the SkipSend Check field to.

    Returns:
        True if either the email is a disposable or presents issues.
    """
    result = False
    try:
        _debug("Checking spam...")
        ssr = requests.get("https://skipsend.com/api/v1/check/", params={"email": {u["email"]}}, timeout=30)
        ssc = ssr.json()
        _debug("Done and JSON got", ssc)

        ssi = "OK"
        if ssc["skip"] == 1:
            _debug("SkipSends says to skip")
            result = True
            reasons = []

            if ssc["disposable"]:
                reasons.append(f"Is a disposable email from {ssc['provider']}")

            if ssc["no_mx"]:
                reasons.append("MX record not found")

            if ssc["cf_routed"]:
                reasons.append("Uses Cloudflare Email Routing")

            ssi = ", ".join(reasons)

        embed.add_embed_field(name="SkipSend Check", value=ssi, inline=False)
        _debug("SkipSends check embed added")
    except requests.exceptions.RequestException as e:
        print("SkipSends request failed. " + str(e))
    except Exception as e:
        print("SkipSends check failed. " + str(e))

    return result


def _check_fakefilter(u: dict, embed: DiscordEmbed) -> bool:
    """Check email domain against FakeFilter, adding results to the embed.

    Args:
        u: Mastodon account object containing the email field.
        embed: Discord embed to append the Disposable Email Check field to.

    Returns:
        True if the email domain is considered fake.
    """
    result = False
    try:
        _debug("Checking FakeFilter...")
        email_domain = u["email"].split("@")[-1]

        if email_domain:
            ffr = requests.get("https://fakefilter.net/api/is/fakedomain/" + email_domain, timeout=30)
            ffc = ffr.json()
            _debug("Done and JSON got", ffc)

            ffi = "OK"
            if ffc["retcode"] == 200 and ffc["isFakeDomain"]:  # noqa: PLR2004
                _debug("FakeFilter says it's fake")
                result = True
                providers = ["DID NOT PASS"]

                if ffc["details"] and "providers" in ffc["details"]:
                    providers = ffc["details"]["providers"]

                ffi = ", ".join(providers)

            embed.add_embed_field(name="FakeFilter Check", value=ffi, inline=False)
            _debug("FakeFilter check embed added")
    except requests.exceptions.RequestException as e:
        print("FakeFilter request failed. " + str(e))
    except Exception as e:
        print("FakeFilter check failed. " + str(e))

    return result


def _reject_registration(u: dict) -> bool:
    """Automatically reject the registration.


    Args:
        u: Mastodon account.

    Returns:
        True if that worked.
    """
    dr = requests.request(
        "POST",
        "{base}/api/v1/admin/accounts/{id}/reject".format(base=cfg.base_url, id=u["id"]),
        headers={"Authorization": "Bearer " + cfg.token},
        timeout=30,
    )
    _debug("Done")

    return dr.status_code == requests.codes.ok


def process_user(db: sqlite3.Connection, u: dict) -> None:  # noqa: PLR0915, C901
    """Send a Discord notification for a newly registered user.

    1. Skips users already recorded in the database.
    2. Checks email and IP against:
        - StopForumSpam
        - SkipSend
        - FakeFilter
    3. Posts a summary embed to the configured Discord webhook
    4. Records the user in the database

    Args:
        u: Mastodon account object from the admin accounts API response.

    Raises:
        RuntimeError: If the database connection is not initialized.
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
        skipsend_flagged = False
        fakefilter_flagged = False
    else:
        spam_flagged = _check_spam(u, embed)
        skipsend_flagged = _check_skipsend(u, embed)
        fakefilter_flagged = _check_fakefilter(u, embed)

    webhook.add_embed(embed)

    if cfg.discord_uid and not (spam_flagged or skipsend_flagged or fakefilter_flagged):
        _debug("Will ping admin")
        webhook.content = f"<@{cfg.discord_uid}>"
    elif cfg.reject_disposable and (skipsend_flagged or fakefilter_flagged):
        _debug("Will reject disposable registration")
        if _reject_registration(u):
            webhook.content = "Registration automatically denied"

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
    # @TODO: Use v2 API
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

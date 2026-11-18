import datetime
import sqlite3
import sys
import time
from pathlib import Path
from shutil import copyfile

import dns.resolver
import dns.reversename
import geoip2.database
import geoip2.errors
import requests
from discord_webhook import DiscordEmbed, DiscordWebhook

import config as cfg

resolver = dns.resolver.Resolver()
resolver.lifetime = 5.0


def _debug(msg: str, obj: object = "") -> None:
    """Print a timestamped debug message when DEBUG_MODE is enabled.

    Args:
        msg: The message text to print.
        obj: An optional value to append after the message.
    """
    if cfg.DEBUG_MODE:
        now = datetime.datetime.now(tz=datetime.UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
        print("[" + now + "] " + msg, obj)


def _reverse_labels(ip: str) -> str:
    """Reverse an IP for DNS-based lookups (`1.2.3.4` becomes `4.3.2.1`, IPv6 is reversed per nibble).

    Args:
        ip: IPv4 or IPv6 address.

    Returns:
        The reversed labels.
    """
    name = dns.reversename.from_address(ip).to_text(omit_final_dot=True)
    return name.removesuffix(".in-addr.arpa").removesuffix(".ip6.arpa")


def _dns_txt(name: str) -> str | None:
    """Get the first TXT record of a name.

    Args:
        name: The DNS name to query.

    Returns:
        The record text, or None if there is no such record.
    """
    try:
        return b"".join(resolver.resolve(name, "TXT")[0].strings).decode(errors="replace")
    except dns.resolver.NXDOMAIN, dns.resolver.NoAnswer:
        # ¯\_ (ツ)_/¯
        return None


def _add_ip_info(u: dict, embed: DiscordEmbed) -> None:
    """Add a row with the IP and hostname, network (ASN) and country to the embed.

    Args:
        u: Mastodon account object containing the ip field.
        embed: Discord embed to append the IP, Network and GeoIP fields to.
    """
    ip = u.get("ip")
    if not ip:
        return

    _debug("Gathering IP info...")
    hostname = None
    network = "Unknown"
    country = "Unknown"

    try:
        hostname = str(resolver.resolve_address(ip)[0].target).rstrip(".")
    except dns.resolver.NXDOMAIN, dns.resolver.NoAnswer:
        # ¯\_ (ツ)_/¯
        pass
    except Exception as e:
        print("Reverse DNS failed. " + str(e))

    # Team Cymru ASN lookup
    try:
        origin = _dns_txt(_reverse_labels(ip) + (".origin6.asn.cymru.com" if ":" in ip else ".origin.asn.cymru.com"))
        if origin:
            fields = [f.strip() for f in origin.split("|")]
            asn = fields[0].split()[0]  # May be several ASNs on multi-origin prefixes
            country = fields[2] or "Unknown"
            name = _dns_txt(f"AS{asn}.asn.cymru.com")
            network = f"AS{asn} {name.split('|')[-1].strip() if name else ''}\n`{fields[1]}`"
    except Exception as e:
        print("ASN lookup failed. " + str(e))

    # MaxMind (if available) for a more accurate GeoIP
    if getattr(cfg, "maxmind_db", False):
        try:
            with geoip2.database.Reader(cfg.maxmind_db) as reader:
                resp = reader.country(ip)
            country = f"{resp.country.name} ({resp.country.iso_code})"
        except geoip2.errors.AddressNotFoundError:
            pass
        except Exception as e:
            print("GeoIP lookup failed. " + str(e))

    # Hostnames are attacker-controlled, don't let them break the formatting
    host_value = "`" + hostname.replace("`", "") + "`" if hostname else "No hostname found"
    embed.add_embed_field(name="IP", value=f"`{ip}` ({host_value})  \nGeoIP: {country} \nNetwork: {network}", inline=False)
    _debug("IP info embed added")


def _check_dnsbl(u: dict, embed: DiscordEmbed) -> bool:
    """Check the IP against DNS blocklists, adding results to the embed.

    Args:
        u: Mastodon account object containing the ip field.
        embed: Discord embed to append the Blocklist Check field to.

    Returns:
        True if the IP is listed on at least one blocklist.
    """
    ip = u.get("ip")
    if not ip:
        return False

    _debug("Checking DNSBLs...")
    result = False
    labels = _reverse_labels(ip)
    lines = []
    checked = 0

    # (name, zone, supports IPv6)
    dnsbls = (
        ("Spamhaus", "zen.spamhaus.org", True),
        ("SpamCop", "bl.spamcop.net", False),
        ("UCEPROTECT", "dnsbl-1.uceprotect.net", False),
        ("DroneBL", "dnsbl.dronebl.org", False),
        ("EFnet RBL", "rbl.efnetrbl.org", False),
    )

    for name, zone, has_ipv6 in dnsbls:
        if ":" in ip and not has_ipv6:
            continue

        try:
            codes = [r.to_text() for r in resolver.resolve(f"{labels}.{zone}", "A")]
        except dns.resolver.NXDOMAIN, dns.resolver.NoAnswer:
            codes = []
        except Exception as e:
            print(f"{name} lookup failed. {e}")
            lines.append(f"{name}: lookup failed")
            continue

        # 127.255.255.x means the query was refused (public resolver, rate limit...)
        if any(c.startswith("127.255.255.") for c in codes):
            lines.append(f"{name}: query refused (public resolver or rate limited?)")
            continue

        checked += 1
        if name == "Spamhaus":
            # Spamhaus has those codes for "residential/dynamic range"
            # They're not abuse by themselves, so filter them out
            codes = [c for c in codes if c not in {"127.0.0.10", "127.0.0.11"}]
        if codes:
            _debug(f"IP listed on {name}", codes)
            result = True
            lines.append(f"{name}: LISTED ({', '.join(codes)})")

    embed.add_embed_field(name="Blocklist Check", value="\n".join(lines) or f"OK ({checked} lists checked)", inline=False)
    _debug("DNSBL check embed added")

    return result


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

        embed.add_embed_field(name="StopForumSpam Email Check", value=sce, inline=False)

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

        embed.add_embed_field(name="StopForumSpam IP Check", value=sci, inline=False)
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
    2. Adds IP details (hostname, ASN, location)
    3. Checks email and IP against:
        - StopForumSpam
        - SkipSend
        - FakeFilter
        - DNS blocklists (Spamhaus, SpamCop, UCEPROTECT, DroneBL, EFnet RBL)
    4. Posts a summary embed to the configured Discord webhook
    5. Records the user in the database

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

    embed.add_embed_field(name="Username", value=f"`{u['username']}`")
    embed.add_embed_field(name="Locale", value=f"`{u['locale']}`")
    embed.add_embed_field(name="Email", value=f"`{u['email']}`", inline=False)
    _add_ip_info(u, embed)

    if cfg.DRY_RUN:
        print("DRY_RUN set, not checking user")
        spam_flagged = False
        skipsend_flagged = False
        fakefilter_flagged = False
        dnsbl_flagged = False
    else:
        spam_flagged = _check_spam(u, embed)
        skipsend_flagged = _check_skipsend(u, embed)
        fakefilter_flagged = _check_fakefilter(u, embed)
        dnsbl_flagged = _check_dnsbl(u, embed)

    webhook.add_embed(embed)

    if cfg.discord_uid and not (spam_flagged or skipsend_flagged or fakefilter_flagged or dnsbl_flagged):
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

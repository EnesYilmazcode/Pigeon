"""Cache each company's logo next to contacts.json, once.

A company's domain comes from a contact's `domain` field, or else from a
company email address. Each logo is downloaded once into logos/, so opening the
page never asks a third party about your pipeline. Companies with no logo
found show a monogram instead.

Run:  python fetch_logos.py [--data path/to/contacts.json]
"""
import argparse
import io
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# A personal address says nothing about where someone works.
FREE_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
             "yahoo.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com"}

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
EXTS = (".svg", ".png", ".jpg", ".ico")


def domain_of(row):
    d = (row.get("domain") or "").strip().lower()
    if d:
        return d
    email = (row.get("email") or "").strip().lower()
    if "@" in email:
        d = email.rsplit("@", 1)[1]
        if d not in FREE_MAIL:
            return d
    return ""


def slug(company):
    return "".join(ch if ch.isalnum() else "-" for ch in company.lower()).strip("-")


def sources(domain):
    return [
        "https://www.google.com/s2/favicons?domain=%s&sz=128" % domain,
        "https://icons.duckduckgo.com/ip3/%s.ico" % domain,
    ]


def grab(domain):
    """Return (bytes, extension) for the first source that gives a real image."""
    for url in sources(domain):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=12) as r:
                blob = r.read()
                ctype = (r.headers.get("Content-Type") or "").lower()
        except Exception:
            continue  # unknown domains come back 404
        if len(blob) < 100:
            continue
        if "svg" in ctype:
            ext = ".svg"
        elif "jpeg" in ctype or "jpg" in ctype:
            ext = ".jpg"
        elif "icon" in ctype:
            ext = ".ico"
        elif "image" in ctype:
            ext = ".png"
        else:
            continue
        return blob, ext
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=os.path.join(HERE, "contacts.json"))
    data = os.path.abspath(ap.parse_args().data)
    logos = os.path.join(os.path.dirname(data), "logos")
    if not os.path.isdir(logos):
        os.makedirs(logos)

    with io.open(data, encoding="utf-8") as f:
        rows = json.load(f)

    domains = {}
    for r in rows:
        c = r.get("company") or ""
        if c and not domains.get(c):
            domains[c] = domain_of(r)

    cache = {}
    for company, domain in domains.items():
        if not domain:
            print("  %-22s no domain, will show a monogram" % company)
            cache[company] = ("", "")
            continue
        name = slug(company)
        existing = [e for e in EXTS if os.path.exists(os.path.join(logos, name + e))]
        if existing:
            print("  %-22s cached %s" % (company, name + existing[0]))
            cache[company] = (domain, "logos/" + name + existing[0])
            continue
        blob, ext = grab(domain)
        if not blob:
            print("  %-22s no logo found, will show a monogram" % company)
            cache[company] = (domain, "")
            continue
        with io.open(os.path.join(logos, name + ext), "wb") as f:
            f.write(blob)
        print("  %-22s saved %s (%d bytes)" % (company, name + ext, len(blob)))
        cache[company] = (domain, "logos/" + name + ext)

    # Merge the two fields in without touching anything else on the record.
    for r in rows:
        domain, logo = cache.get(r.get("company") or "", ("", ""))
        r["domain"] = domain
        r["logo"] = logo

    tmp = data + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(rows, ensure_ascii=False, indent=1))
    os.replace(tmp, data)
    print("\nupdated %d contacts across %d companies" % (len(rows), len(domains)))


if __name__ == "__main__":
    main()

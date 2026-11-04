"""بوت تيليجرام: بيبعتلك الأفلام اللي نزلت في VOX City Centre Almaza."""
import os
import re
import sys
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

BASE = "https://egy.voxcinemas.com"
WHATSON = f"{BASE}/movies/whatson"
CINEMA_CODE = "0047"  # كود فرع الماظة في لينكات الحجز /booking/0047-xxxxx
CINEMA_NAME = "City Centre Almaza"
INTERVAL = int(os.getenv("INTERVAL", "300"))  # 5 دقايق
MAX_DAYS = int(os.getenv("MAX_DAYS", "7"))  # كام يوم قدام يفحص
SEEN_FILE = "seen.json"

http = requests.Session()
http.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
})


def get_soup(url):
    r = http.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def get_movies():
    """كل الأفلام في صفحة What's On: {slug: title}"""
    soup = get_soup(WHATSON)
    movies = {}
    for a in soup.select("a[href*='/movies/']"):
        path = urlparse(urljoin(BASE, a["href"])).path
        m = re.fullmatch(r"/movies/([^/]+)", path)
        if not m or m.group(1) in ("whatson", "comingsoon"):
            continue
        slug = m.group(1)
        movies.setdefault(slug, "")
        title = a.get_text(strip=True)
        if title:
            movies[slug] = title
    for slug, title in movies.items():
        if not title:
            movies[slug] = slug.replace("-", " ").title()
    return movies


def session_format(a):
    """نوع الحفلة (Standard / IMAX / 4DX / Gold ...) من القائمة اللي فيها لينك الحجز"""
    for lst in a.find_parents(["ul", "ol"]):
        li = lst.find_parent("li")
        if li:
            tag = li.find(["strong", "b"])
            if tag and tag.get_text(strip=True):
                return tag.get_text(strip=True)
            first = next(li.stripped_strings, "")
            if first:
                return first
    return "Standard"


def cinema_sessions(soup):
    """حفلات فرع الماظة بس من صفحة الفيلم: [(الوقت, لينك الحجز, النوع)]"""
    out = []
    for a in soup.select("a[href*='/booking/']"):
        href = a["href"]
        code = href.split("/booking/")[-1].split("-")[0]
        if code == CINEMA_CODE:
            out.append((a.get_text(strip=True), urljoin(BASE, href), session_format(a)))
    return out


def almaza_info(slug):
    """بيرجع (التاريخ, الحفلات, اللغة, لينك الصفحة) لأول يوم فيه حجز في الماظة"""
    url = f"{BASE}/movies/{slug}"
    soup = get_soup(url)
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Language:\s*(\S+)", text)
    lang = m.group(1) if m else ""

    sessions = cinema_sessions(soup)
    if sessions:
        return "النهاردة", sessions, lang, url + "#showtimes"

    dates = []
    for a in soup.select("a[href*='?d=']"):
        m = re.search(r"d=(\d{8})", a["href"])
        if m and m.group(1) not in dates:
            dates.append(m.group(1))
    for d in dates[: MAX_DAYS - 1]:
        time.sleep(0.5)
        day_url = f"{url}?d={d}"
        sessions = cinema_sessions(get_soup(day_url))
        if sessions:
            label = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            return label, sessions, lang, day_url + "#showtimes"
    return None, [], lang, url


def send(text):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=30,
    )
    r.raise_for_status()


def load_state():
    if not os.path.exists(SEEN_FILE):
        return None
    with open(SEEN_FILE, encoding="utf-8") as f:
        return set(json.load(f))


def save_state(notified):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(notified), f, ensure_ascii=False, indent=2)


def check():
    movies = get_movies()
    if not movies:
        raise RuntimeError("مفيش أفلام اتلقت - شكل الصفحة ممكن يكون اتغير")

    state = load_state()
    first_run = state is None
    notified = set(state or [])

    for slug, title in movies.items():
        if slug in notified:
            continue
        try:
            day, sessions, lang, link = almaza_info(slug)
        except Exception as e:
            print(f"تعذر فحص {slug}: {e}")
            continue
        time.sleep(1)
        if not sessions:
            continue  # لسه مفيش حجز في الماظة، هنفحصه تاني المرة الجاية
        notified.add(slug)
        if not first_run:
            by_fmt = {}
            for t, u, f in sessions:
                by_fmt.setdefault(f, []).append((t, u))
            lines = []
            for f, items in by_fmt.items():
                times = " | ".join(t for t, _ in items)
                lines.append(f"🎞 {f}: {times}\n🎟 {items[0][1]}")
            send(
                f"🎬 {title} {f'({lang})' if lang else ''}\n"
                f"📍 {CINEMA_NAME}\n"
                f"📅 {day}\n\n" + "\n\n".join(lines) +
                f"\n\n🔗 كل المواعيد: {link}"
            )
            print("اتبعت:", title)

    notified &= set(movies)  # لو فيلم اتشال وراجع تاني يتبعت تاني
    save_state(notified)
    print(f"أول تشغيل: {first_run} | أفلام متابَعة: {len(notified)}")


if __name__ == "__main__":
    if "--once" in sys.argv:
        check()
    else:
        while True:
            try:
                check()
            except Exception as e:
                print("خطأ:", e)
            time.sleep(INTERVAL)

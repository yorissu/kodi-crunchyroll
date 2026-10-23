"""Crunchyroll (QR) - Kodi video plugin router."""
import json
import os
import sys
from urllib.parse import parse_qsl, urlencode, quote

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib import proxy
from resources.lib.api import Api, ApiError, LoginRequired, LICENSE_URL
from resources.lib.login import run_login

ADDON = xbmcaddon.Addon()
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
BASE_URL = sys.argv[0]
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].lstrip("-").isdigit() else -1
ASK = "Ask every time"
KODI_MAJOR =int(xbmc.getInfoLabel("System.BuildVersion").split(".")[0] or 21)

api = Api(PROFILE, ADDON.getSetting("locale") or "en-US")


def url(**kw):
    return BASE_URL + "?" + urlencode(kw)


# ---- list item helpers ----

def best_image(images, key):
    """images[key] is a list of size-variant lists; pick the widest."""
    variants = (images or {}).get(key) or []
    if variants and isinstance(variants[0], list):
        variants = variants[0]
    if not variants:
        return ""
    return max(variants, key=lambda v: v.get("width", 0)).get("source", "")


def add_dir(label, action, art=None, plot="", **params):
    li = xbmcgui.ListItem(label)
    if art:
        li.setArt(art)
    if plot:
        li.getVideoInfoTag().setPlot(plot)
    xbmcplugin.addDirectoryItem(HANDLE, url(action=action, **params), li, isFolder=True)


def add_object(obj, playheads=None):
    """Adds any Crunchyroll panel/object (series, season, episode, movie...)."""
    kind = obj.get("type")
    images = obj.get("images") or {}
    title = obj.get("title") or obj.get("name") or ""
    plot = obj.get("description") or ""
    if kind in ("series", "movie_listing"):
        art = {"poster": best_image(images, "poster_tall"), "fanart": best_image(images, "poster_wide"),
               "thumb": best_image(images, "poster_tall")}
        add_dir(title, "series" if kind == "series" else "movies", art, plot, id=obj["id"], title=title)
    elif kind == "season":
        add_dir(title, "episodes", plot=plot, id=obj["id"])
    elif kind in ("episode", "movie"):
        meta = obj.get("episode_metadata") or obj.get("movie_metadata") or obj
        series = meta.get("series_title") or meta.get("movie_listing_title") or ""
        num = meta.get("episode_number") or meta.get("episode") or meta.get("sequence_number")
        if isinstance(num, float) and num.is_integer():
            num = int(num)
        elif isinstance(num, str) and num.isdigit():
            num = int(num)
        label = title
        if kind == "episode" and num:
            label = "{}. {}".format(num, title)
        if obj.get("_show_series") and series:
            label = "{} - {}".format(series, label)
        li = xbmcgui.ListItem(label)
        thumb = best_image(images, "thumbnail")
        li.setArt({"thumb": thumb, "fanart": thumb})
        tag = li.getVideoInfoTag()
        tag.setTitle(label)  # skins show the info title in episode views, so it carries the number
        tag.setPlot(plot)
        tag.setMediaType("episode" if kind == "episode" else "movie")
        duration = int((meta.get("duration_ms") or 0) / 1000)
        if duration:
            tag.setDuration(duration)
        if kind == "episode":
            tag.setTvShowTitle(series)
            if isinstance(num, int):
                tag.setEpisode(num)
            if isinstance(meta.get("season_number"), int):
                tag.setSeason(meta["season_number"])
        ph = (playheads or {}).get(obj["id"]) or {}
        pos = obj.get("playhead", ph.get("playhead", 0))
        watched = obj.get("fully_watched", ph.get("fully_watched", False))
        if watched:
            tag.setPlaycount(1)
        elif pos and duration:
            tag.setResumePoint(pos, duration)
        li.setProperty("IsPlayable", "true")
        li.addContextMenuItems([("Choose audio language",
                                 "PlayMedia({})".format(url(action="play", id=obj["id"], audio=ASK)))])
        xbmcplugin.addDirectoryItem(HANDLE, url(action="play", id=obj["id"]), li, isFolder=False)


def unwrap(items):
    """Watchlist/history wrap objects in 'panel'; copy playhead info onto the panel."""
    out = []
    for it in items:
        panel = it.get("panel")
        if panel:
            panel = dict(panel)
            for k in ("playhead", "fully_watched"):
                if k in it:
                    panel[k] = it[k]
            out.append(panel)
        else:
            out.append(it)
    return out


def end(content="videos", cache=True):
    xbmcplugin.setContent(HANDLE, content)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=cache)


# ---- routes ----

def root():
    if not api.logged_in():
        add_dir("[B]Sign in with QR code[/B]", "login")
        end(cache=False)
        return
    add_dir("Continue watching", "continue")
    add_dir("Watchlist", "watchlist")
    add_dir("Search", "search")
    add_dir("Popular", "browse", sort="popularity")
    add_dir("Newly added", "browse", sort="newly_added")
    add_dir("A-Z", "browse", sort="alphabetical")
    add_dir("Genres", "categories")
    add_dir("History", "history")
    name = api.session.get("profile_name")
    add_dir("Profile: {}".format(name) if name else "Switch profile", "profiles")
    end(cache=False)


def list_objects(items, content="tvshows", show_series=False):
    items = unwrap(items)
    ids = [o["id"] for o in items if o.get("type") in ("episode", "movie") and "playhead" not in o]
    heads = api.playheads(ids)
    for o in items:
        if show_series:
            o["_show_series"] = True
        add_object(o, heads)
    return content


def r_continue(p):
    list_objects(api.continue_watching().get("data", []), show_series=True)
    end("episodes", cache=False)


def r_watchlist(p):
    list_objects(api.watchlist().get("data", []))
    end("tvshows", cache=False)


def r_history(p):
    page = int(p.get("page", 1))
    data = api.history(page=page)
    list_objects(data.get("data", []), show_series=True)
    if data.get("data"):
        add_dir("Next page >>", "history", page=page + 1)
    end("episodes", cache=False)


def r_browse(p):
    start = int(p.get("start", 0))
    data = api.browse(start=start, sort_by=p.get("sort", "popularity"), categories=p.get("cat"))
    items = data.get("data", [])
    list_objects(items)
    total = data.get("total", 0)
    if items and start + len(items) < total:
        kw = {"sort": p.get("sort", "popularity"), "start": start + len(items)}
        if p.get("cat"):
            kw["cat"] = p["cat"]
        add_dir("Next page >>", "browse", **kw)
    end("tvshows")


def r_categories(p):
    for c in api.categories().get("items", []):
        cid = c.get("tenant_category") or c.get("id")
        title = (c.get("localization") or {}).get("title") or cid
        add_dir(title, "browse", sort="popularity", cat=cid)
    end("files")


def r_search(p):
    query = p.get("q") or xbmcgui.Dialog().input("Search Crunchyroll")
    if not query:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for group in api.search(query).get("data", []):
        for o in group.get("items", []):
            if o.get("type") == "episode":
                o["_show_series"] = True
            add_object(o)
    end("tvshows", cache=False)


def r_series(p):
    seasons = api.seasons(p["id"]).get("data", [])
    if len(seasons) == 1:
        return r_episodes({"id": seasons[0]["id"]})
    for s in seasons:
        s.setdefault("type", "season")
        add_object(s)
    end("seasons")


def typed(items, kind):
    """cms list endpoints omit 'type' on their items."""
    for it in items:
        it.setdefault("type", kind)
    return items


def r_episodes(p):
    list_objects(typed(api.episodes(p["id"]).get("data", []), "episode"))
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_EPISODE)
    end("episodes", cache=False)


def r_movies(p):
    list_objects(typed(api.movies(p["id"]).get("data", []), "movie"))
    end("movies", cache=False)


AVATAR_URL = "https://static.crunchyroll.com/assets/avatar/170x170/{}"


def choose_profile(force=False):
    """Asks which profile to use. Without force, only asks when there is more than one."""
    profiles = api.profiles()
    if not profiles or (len(profiles) == 1 and not force):
        if profiles:
            api.switch_profile(profiles[0])
        return False
    items = []
    for pr in profiles:
        li = xbmcgui.ListItem(pr.get("profile_name") or pr.get("username") or pr["profile_id"])
        if pr.get("avatar"):
            li.setArt({"icon": AVATAR_URL.format(pr["avatar"]), "thumb": AVATAR_URL.format(pr["avatar"])})
        items.append(li)
    current = next((i for i, pr in enumerate(profiles) if pr.get("profile_id") == api.session.get("profile_id")), -1)
    idx = xbmcgui.Dialog().select("Who's watching?", items, preselect=current, useDetails=True)
    if idx < 0:
        return False
    api.switch_profile(profiles[idx])
    return True


def r_profiles(p):
    if choose_profile(force=True):
        xbmc.executebuiltin("Container.Refresh")


def r_login(p):
    if run_login(api, PROFILE):
        choose_profile()
        xbmc.executebuiltin("Container.Refresh")


def r_logout(p):
    api.logout()
    xbmcgui.Dialog().notification("Crunchyroll", "Signed out", xbmcgui.NOTIFICATION_INFO, 3000)
    xbmc.executebuiltin("Container.Refresh")


# ---- playback ----

LANGUAGES = {
    "ja-JP": "Japanese", "en-US": "English", "de-DE": "German", "es-419": "Spanish (Latin America)",
    "es-ES": "Spanish (Spain)", "fr-FR": "French", "it-IT": "Italian", "pt-BR": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)", "ru-RU": "Russian", "ar-SA": "Arabic", "hi-IN": "Hindi",
    "ta-IN": "Tamil", "te-IN": "Telugu", "zh-CN": "Chinese", "ko-KR": "Korean", "th-TH": "Thai",
    "id-ID": "Indonesian", "ms-MY": "Malay", "vi-VN": "Vietnamese", "pl-PL": "Polish",
}


def pick_version(guid):
    """Shows the audio language picker. Returns the guid to play, or None if cancelled."""
    versions = [v for v in api.versions(guid) if v.get("guid")]
    if len(versions) < 2:
        return guid
    versions.sort(key=lambda v: (not v.get("original"), v.get("audio_locale") != "en-US"))
    labels = []
    for v in versions:
        loc = v.get("audio_locale", "")
        label = LANGUAGES.get(loc, loc)
        if v.get("original"):
            label += " (original)"
        labels.append(label)
    current = next((i for i, v in enumerate(versions) if v["guid"] == guid), 0)
    idx = xbmcgui.Dialog().select("Audio language", labels, preselect=current)
    return versions[idx]["guid"] if idx >= 0 else None


def lang_code(locale):
    return (locale or "und").split("-")[0].lower()


def download_subtitles(stream):
    sub_dir = os.path.join(PROFILE, "subs")
    os.makedirs(sub_dir, exist_ok=True)
    for f in os.listdir(sub_dir):
        try:
            os.remove(os.path.join(sub_dir, f))
        except OSError:
            pass
    paths = []
    subs = dict(stream.get("subtitles") or {})
    for loc, s in (stream.get("captions") or {}).items():
        subs.setdefault(loc + "-cc", s)
    for loc, s in subs.items():
        if not s.get("url") or loc == "none":
            continue
        path = os.path.join(sub_dir, "{}.{}.{}".format(loc, lang_code(loc), s.get("format") or "ass"))
        try:
            from urllib.request import urlopen
            with urlopen(s["url"], timeout=15) as r, open(path, "wb") as out:
                out.write(r.read())
            paths.append(path)
        except OSError:
            pass
    return paths


def r_play(p):
    import inputstreamhelper
    if not inputstreamhelper.Helper("mpd", drm="com.widevine.alpha").check_inputstream():
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    audio = p.get("audio") or ADDON.getSetting("audio") or ASK
    if audio == ASK:
        guid = pick_version(p["id"])
        if not guid:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
        stream = api.play(guid)
    else:
        stream = api.play(p["id"], audio=audio)
    guid, token = stream["guid"], stream.get("token")
    xbmc.log("[crunchyrollqr] playing {} manifest {}".format(guid, stream["url"].split("?")[0]), xbmc.LOGINFO)
    server = proxy.start(api)

    li = xbmcgui.ListItem(path=proxy.proxied(server, stream["url"]))
    li.setMimeType("application/dash+xml")
    li.setContentLookup(False)
    li.setProperty("inputstream", "inputstream.adaptive")
    headers = api.license_headers(guid, token)
    if KODI_MAJOR >= 22:
        li.setProperty("inputstream.adaptive.drm", json.dumps({"com.widevine.alpha": {"license": {
            "server_url": LICENSE_URL,
            "req_headers": urlencode(headers, quote_via=quote),
            "unwrapper": "json,base64",
            "unwrapper_params": {"path_data": "license"},
        }}}))
    else:
        if KODI_MAJOR < 21:
            li.setProperty("inputstream.adaptive.manifest_type", "mpd")
        li.setProperty("inputstream.adaptive.license_type", "com.widevine.alpha")
        li.setProperty("inputstream.adaptive.license_key",
                       LICENSE_URL + "|" + urlencode(headers, quote_via=quote) + "|R{SSM}|JBlicense")
    # always pick the highest available quality instead of adapting to bandwidth
    li.setProperty("inputstream.adaptive.stream_selection_type", "fixed-res")
    li.setProperty("inputstream.adaptive.chooser_resolution_max", "max")
    li.setProperty("inputstream.adaptive.chooser_resolution_secure_max", "max")
    li.setProperty("inputstream.adaptive.manifest_headers", "User-Agent=" + quote(api.ua))
    li.setProperty("inputstream.adaptive.stream_headers", "User-Agent=" + quote(api.ua))
    subs = download_subtitles(stream)
    if subs:
        li.setSubtitles(subs)
    xbmcplugin.setResolvedUrl(HANDLE, True, li)
    try:
        watch(guid, token)
    finally:
        server.shutdown()


def watch(guid, token):
    """Stay alive while playing: sync playhead, then release the stream slot."""
    player, monitor = xbmc.Player(), xbmc.Monitor()
    for _ in range(120):
        if player.isPlayingVideo() or monitor.waitForAbort(0.5):
            break
    pos, last_sync = 0, 0
    try:
        playing = player.getPlayingFile() if player.isPlayingVideo() else None
        while playing and player.isPlayingVideo() and player.getPlayingFile() == playing:
            pos = player.getTime()
            if pos - last_sync >= 30 or pos < last_sync:
                api.set_playhead(guid, pos)
                last_sync = pos
            if monitor.waitForAbort(1):
                break
    except RuntimeError:
        pass
    if pos:
        api.set_playhead(guid, pos)
    if token:
        api.delete_stream(guid, token)


ROUTES = {
    "continue": r_continue, "watchlist": r_watchlist, "history": r_history, "browse": r_browse,
    "categories": r_categories, "search": r_search, "series": r_series, "episodes": r_episodes,
    "movies": r_movies, "play": r_play, "login": r_login, "logout": r_logout, "profiles": r_profiles,
}


def main():
    params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    action = params.get("action")
    try:
        if not action:
            root()
        else:
            ROUTES[action](params)
    except LoginRequired as e:
        xbmcgui.Dialog().notification("Crunchyroll", str(e), xbmcgui.NOTIFICATION_WARNING, 4000)
        if HANDLE >= 0:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        run_login(api, PROFILE)
        xbmc.executebuiltin("Container.Refresh")
    except ApiError as e:
        xbmc.log("[crunchyrollqr] " + str(e), xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Crunchyroll", str(e))
        if action == "play":
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


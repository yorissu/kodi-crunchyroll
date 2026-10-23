"""Crunchyroll API client: device-code (QR) login, token refresh, catalog, playback."""
import json
import os
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://www.crunchyroll.com"
# Crunchyroll rotates app credentials; crunchy-labs keeps this file current automatically.
CREDENTIALS_URL = "https://raw.githubusercontent.com/crunchy-labs/artifacts/refs/heads/main/credentials.json"
FALLBACK_TV = {
    "basic_auth_token": "ZXI5bmdnMmtvNW9oaXJsYTUxaTI6VmwxVDBQbjhRWko2d3o0NnhYRGxIekRGUDV0Wlgxb3E=",
    "version": "3.76.0",
    "version_code": "22366",
}
PLAY_URLS = [
    BASE + "/playback/v2/{id}/tv/android_tv/play",
    BASE + "/playback/v3/{id}/tv/android_tv/play",
]
TOKEN_DELETE_URLS = [
    "https://cr-play-service.prd.crunchyrollsvc.com/v1/token/{id}/{token}",
    BASE + "/playback/v1/token/{id}/{token}",
]
LICENSE_URL = "https://cr-license-proxy.prd.crunchyrollsvc.com/v1/license/widevine"
DEVICE_TYPE = "Kodi"
DEVICE_NAME = "Kodi"


class ApiError(Exception):
    pass


class LoginRequired(ApiError):
    pass


class Api:
    def __init__(self, profile_dir, locale="en-US"):
        self.dir = profile_dir
        self.locale = locale
        os.makedirs(profile_dir, exist_ok=True)
        self.session = self._load("session.json") or {}
        self.device_id = self._device_id()
        self.creds = self._credentials()
        self.ua = "Crunchyroll/ANDROIDTV/{}_{} (Android 14; en-US; Chromecast)".format(
            self.creds["version"], self.creds["version_code"])

    # ---- local storage ----

    def _path(self, name):
        return os.path.join(self.dir, name)

    def _load(self, name):
        try:
            with open(self._path(name), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _store(self, name, data):
        with open(self._path(name), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _device_id(self):
        dev = self._load("device.json")
        if not dev:
            dev = {"device_id": str(uuid.uuid4())}
            self._store("device.json", dev)
        return dev["device_id"]

    def _credentials(self):
        cached = self._load("credentials.json")
        if cached and cached.get("fetched", 0) > time.time() - 86400:
            return cached["tv"]
        try:
            with urlopen(CREDENTIALS_URL, timeout=10) as r:
                tv = json.loads(r.read())["android_tv"]
            self._store("credentials.json", {"fetched": time.time(), "tv": tv})
            return tv
        except (URLError, OSError, ValueError, KeyError):
            return cached["tv"] if cached else FALLBACK_TV

    # ---- HTTP ----

    def _request(self, method, url, params=None, json_body=None, form=None, auth=True):
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        headers = {"User-Agent": self.ua}
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if auth == "basic":
            headers["Authorization"] = "Basic " + self.creds["basic_auth_token"]
        elif auth:
            headers["Authorization"] = "Bearer " + self.access_token()
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=20) as r:
                return r.status, r.read()
        except HTTPError as e:
            return e.code, e.read()
        except URLError as e:
            raise ApiError("Network error: {}".format(e.reason))

    def _json(self, method, url, params=None, json_body=None, retry=True):
        status, body = self._request(method, url, params, json_body)
        if status == 401 and retry:
            self.session["expires_at"] = 0
            return self._json(method, url, params, json_body, retry=False)
        if status >= 400:
            raise ApiError("HTTP {}: {}".format(status, body[:300].decode("utf-8", "replace")))
        return json.loads(body) if body else {}

    def get(self, path, **params):
        params.setdefault("locale", self.locale)
        return self._json("GET", BASE + path, params)

    # ---- auth ----

    def logged_in(self):
        return bool(self.session.get("refresh_token"))

    def logout(self):
        self.session = {}
        try:
            os.remove(self._path("session.json"))
        except OSError:
            pass

    def _device_form(self, **extra):
        form = {"scope": "offline_access", "device_id": self.device_id,
                "device_type": DEVICE_TYPE, "device_name": DEVICE_NAME}
        form.update(extra)
        return form

    def _save_token(self, j):
        self.session.update({
            "access_token": j["access_token"],
            "refresh_token": j.get("refresh_token") or self.session.get("refresh_token"),
            "expires_at": time.time() + int(j.get("expires_in", 300)) - 30,
            "account_id": j.get("account_id") or self.session.get("account_id"),
            "profile_id": j.get("profile_id") or self.session.get("profile_id"),
        })
        self._store("session.json", self.session)

    def device_code(self):
        """Start QR login. Returns dict with user_code, device_code, interval, expires_in."""
        status, body = self._request("POST", BASE + "/auth/v1/device/code", form={}, auth="basic")
        if status != 200:
            raise ApiError("Could not get activation code (HTTP {})".format(status))
        return json.loads(body)

    def poll_device(self, device_code):
        """True once the code was activated on the phone, False while still pending."""
        status, body = self._request("POST", BASE + "/auth/v1/device/token",
                                     json_body={"device_code": device_code}, auth="basic")
        if status == 204 or not body:
            return False
        if status != 200:
            raise ApiError("Activation failed (HTTP {}): {}".format(status, body[:200].decode("utf-8", "replace")))
        j = json.loads(body)
        if j.get("access_token"):
            self._save_token(j)
        elif j.get("refresh_token"):
            self.session["refresh_token"] = j["refresh_token"]
            self._refresh()
        else:
            return False
        if not self.session.get("account_id"):
            self.session["account_id"] = self._json("GET", BASE + "/accounts/v1/me").get("account_id")
            self._store("session.json", self.session)
        return True

    def _refresh(self):
        if not self.session.get("refresh_token"):
            raise LoginRequired("Not signed in")
        status, body = self._request(
            "POST", BASE + "/auth/v1/token", auth="basic",
            form=self._device_form(grant_type="refresh_token", refresh_token=self.session["refresh_token"]))
        if status != 200:
            if status in (400, 401, 403):
                self.logout()
                raise LoginRequired("Session expired, please sign in again")
            raise ApiError("Token refresh failed (HTTP {})".format(status))
        self._save_token(json.loads(body))

    def access_token(self):
        if not self.session.get("access_token") or self.session.get("expires_at", 0) < time.time():
            self._refresh()
        return self.session["access_token"]

    def profiles(self):
        """List of {profile_id, profile_name, avatar, is_selected, ...}."""
        return self._json("GET", BASE + "/accounts/v1/me/multiprofile").get("profiles", [])

    def switch_profile(self, profile):
        self.access_token()  # make sure the refresh token is still valid
        status, body = self._request(
            "POST", BASE + "/auth/v1/token", auth="basic",
            form=self._device_form(grant_type="refresh_token_profile_id", profile_id=profile["profile_id"],
                                   refresh_token=self.session["refresh_token"]))
        if status != 200:
            raise ApiError("Profile switch failed (HTTP {}): {}".format(
                status, body[:200].decode("utf-8", "replace")))
        self._save_token(json.loads(body))
        self.session["profile_id"] = profile["profile_id"]
        self.session["profile_name"] = profile.get("profile_name") or profile.get("username") or ""
        self._store("session.json", self.session)

    @property
    def account_id(self):
        return self.session.get("account_id")

    # ---- catalog ----

    def browse(self, start=0, sort_by="popularity", categories=None, n=50):
        params = {"start": start, "n": n, "sort_by": sort_by, "type": "series,movie_listing"}
        if categories:
            params["categories"] = categories
        return self.get("/content/v2/discover/browse", **params)

    def categories(self):
        return self.get("/content/v1/tenant_categories")

    def search(self, query, n=50):
        return self.get("/content/v2/discover/search", q=query, n=n, type="series,movie_listing,episode")

    def watchlist(self, n=100):
        return self.get("/content/v2/discover/{}/watchlist".format(self.account_id), n=n, order="desc")

    def continue_watching(self, n=50):
        return self.get("/content/v2/discover/{}/history".format(self.account_id), n=n)

    def history(self, page=1, size=50):
        return self.get("/content/v2/{}/watch-history".format(self.account_id), page=page, page_size=size)

    def seasons(self, series_id):
        return self.get("/content/v2/cms/series/{}/seasons".format(series_id))

    def episodes(self, season_id):
        return self.get("/content/v2/cms/seasons/{}/episodes".format(season_id))

    def movies(self, listing_id):
        return self.get("/content/v2/cms/movie_listings/{}/movies".format(listing_id))

    def versions(self, guid):
        """Audio versions (dubs) of an episode: [{audio_locale, guid, original}, ...]."""
        try:
            data = self.get("/content/v2/cms/objects/{}".format(guid)).get("data") or [{}]
        except ApiError:
            return []
        obj = data[0]
        meta = obj.get("episode_metadata") or obj.get("movie_metadata") or {}
        return obj.get("versions") or meta.get("versions") or []

    def playheads(self, ids):
        if not ids:
            return {}
        try:
            data = self.get("/content/v2/{}/playheads".format(self.account_id), content_ids=",".join(ids))
        except ApiError:
            return {}
        return {p["content_id"]: p for p in data.get("data", [])}

    def set_playhead(self, content_id, seconds):
        try:
            self._request("POST", BASE + "/content/v2/{}/playheads".format(self.account_id),
                          params={"locale": self.locale},
                          json_body={"content_id": content_id, "playhead": int(seconds)})
        except ApiError:
            pass

    # ---- playback ----

    def delete_stream(self, content_id, token):
        for tpl in TOKEN_DELETE_URLS:
            try:
                status, _ = self._request("DELETE", tpl.format(id=content_id, token=token))
                if status < 400:
                    return
            except ApiError:
                pass

    def _play_once(self, guid, audio=None):
        params = {"force_locale": ""}
        if audio:
            params["preferred_audio_language"] = audio
        status, j = 0, {}
        for tpl in PLAY_URLS:
            status, body = self._request("GET", tpl.format(id=guid), params=params)
            try:
                j = json.loads(body)
            except ValueError:
                j = {}
            if status < 400 and j.get("url"):
                break
        return status, j

    def play(self, guid, audio=None):
        """Returns the play response (url, token, subtitles, ...) with 'guid' set to the played id."""
        status, j = self._play_once(guid, audio)
        if status >= 400 and "TOO_MANY_ACTIVE_STREAMS" in json.dumps(j):
            for s in j.get("activeStreams", []):
                self.delete_stream(s.get("contentId") or s.get("content_id"), s.get("token"))
            status, j = self._play_once(guid, audio)
        if status >= 400 or not j.get("url"):
            raise ApiError("Playback failed (HTTP {}): {}".format(status, json.dumps(j)[:300]))
        j["guid"] = guid
        current = j.get("audioLocale") or j.get("audio_locale")
        if audio and current != audio:
            for v in j.get("versions") or []:
                if v.get("audio_locale") == audio and v.get("guid") and v["guid"] != guid:
                    self.delete_stream(guid, j.get("token"))
                    return self.play(v["guid"], audio=None)
        return j

    def license_headers(self, content_id, video_token):
        return {
            "Authorization": "Bearer " + self.access_token(),
            "Content-Type": "application/octet-stream",
            "User-Agent": self.ua,
            "X-Cr-Content-Id": content_id,
            "X-Cr-Video-Token": video_token,
        }

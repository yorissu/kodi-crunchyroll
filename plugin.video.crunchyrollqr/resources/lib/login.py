"""QR-code sign-in dialog (Crunchyroll device activation)."""
import os
import struct
import time
import zlib

import xbmc
import xbmcgui

from . import qr
from .api import ApiError

ACTIVATE_URL = "https://www.crunchyroll.com/activate"
CLOSE_ACTIONS = (9, 10, 13, 92)  # parent dir, previous menu, stop, back


def _solid_png(path):
    """1x1 white PNG, tinted with colorDiffuse as a dialog background."""
    if os.path.exists(path):
        return path

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return path


def _qr_image(profile_dir, url, code):
    try:
        return qr.write_png(url, os.path.join(profile_dir, "qr_{}.png".format(code)))
    except (OSError, ValueError):
        return None


class LoginDialog(xbmcgui.WindowDialog):
    def setup(self, profile_dir, qr_path, code):
        self.cancelled = False
        bg = _solid_png(os.path.join(profile_dir, "white.png"))
        self.addControl(xbmcgui.ControlImage(0, 0, 1280, 720, bg, colorDiffuse="F0101820"))
        if qr_path:
            self.addControl(xbmcgui.ControlImage(90, 150, 420, 420, qr_path))
        else:
            self.addControl(xbmcgui.ControlLabel(90, 340, 420, 40, "(QR unavailable - use the code)",
                                                 textColor="FFAAAAAA"))
        self.addControl(xbmcgui.ControlLabel(570, 160, 650, 50, "Sign in to Crunchyroll", font="font30_title",
                                             textColor="FFF47521"))
        text = ("Scan the QR code with your phone and confirm in the Crunchyroll app or website.\n\n"
                "Or open  crunchyroll.com/activate  and enter:")
        box = xbmcgui.ControlTextBox(570, 230, 650, 160, textColor="FFFFFFFF")
        self.addControl(box)
        box.setText(text)
        self.addControl(xbmcgui.ControlLabel(570, 400, 650, 80, code.upper(), font="font_MainMenu",
                                             textColor="FFFFFFFF"))
        self.status = xbmcgui.ControlLabel(570, 520, 650, 40, "Waiting for confirmation...", textColor="FFAAAAAA")
        self.addControl(self.status)

    def onAction(self, action):
        if action.getId() in CLOSE_ACTIONS:
            self.cancelled = True
            self.close()


def run_login(api, profile_dir):
    """Shows the QR dialog and polls until activated. Returns True on success."""
    try:
        dc = api.device_code()
    except ApiError as e:
        xbmcgui.Dialog().ok("Crunchyroll", str(e))
        return False
    code = dc["user_code"]
    url = "{}?code={}".format(ACTIVATE_URL, code)
    qr = _qr_image(profile_dir, url, code)
    interval = float(dc.get("interval", 5))
    if interval > 60:  # the API reports milliseconds
        interval /= 1000.0
    interval = max(interval, 2.0)
    deadline = time.time() + int(dc.get("expires_in", 300))

    dlg = LoginDialog()
    dlg.setup(profile_dir, qr, code)
    dlg.show()
    monitor = xbmc.Monitor()
    ok = False
    try:
        while not dlg.cancelled and time.time() < deadline:
            if monitor.waitForAbort(interval):
                break
            try:
                if api.poll_device(dc["device_code"]):
                    ok = True
                    break
            except ApiError as e:
                dlg.close()
                xbmcgui.Dialog().ok("Crunchyroll", str(e))
                return False
    finally:
        dlg.close()
        del dlg
        if qr:
            try:
                os.remove(qr)
            except OSError:
                pass
    if ok:
        xbmcgui.Dialog().notification("Crunchyroll", "Signed in", xbmcgui.NOTIFICATION_INFO, 3000)
    elif time.time() >= deadline:
        xbmcgui.Dialog().ok("Crunchyroll", "The code expired. Open the add-on again for a new one.")
    return ok

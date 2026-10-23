
# Crunchyroll (QR) for Kodi

Unofficial Kodi add-on for [Crunchyroll](https://www.crunchyroll.com). You sign in by scanning a QR code with your phone, then watch everything your account can watch. Works on Kodi 20 or newer.

## Installation

Done once, in Kodi. Menu names are from Kodi 21 with the default skin.

1. **Allow outside add-ons:** Settings → System → Add-ons → switch on **Unknown sources** → Yes.
2. **Add the source:** Settings → File manager → **Add source** → `<None>` → type `https://yorissu.github.io/kodi-crunchyroll/` → OK → name it `crunchyroll` → OK.
3. **Install the repository:** Add-ons → add-on browser (box icon, top left) → **Install from zip file** → `crunchyroll` → `repository.crunchyrollqr-….zip`.
4. **Install the add-on:** add-on browser → **Install from repository** → Crunchyroll (QR) repository → Video add-ons → **Crunchyroll (QR)** → Install → OK.

## Usage

- **Sign in:** open Crunchyroll (QR) → **Sign in with QR code**. Scan the code with your phone and confirm, or open crunchyroll.com/activate and type the code shown. No password is stored in Kodi. The QR code is drawn by the add-on itself; nothing is sent to a third party.
- **Profiles:** after signing in you pick a profile if the account has several. Switch later with **Profile: …** in the main menu.
- **First playback:** Kodi asks to install Widevine (needed for Crunchyroll's video protection). Answer Yes.
- **Browse:** Continue watching, Watchlist, Search, Popular, Newly added, A-Z, Genres, History. Episodes are numbered and show your watch progress.
- **Audio language:** episodes with dubs ask which language to play (original first). Set a fixed language in the add-on settings, or use **Choose audio language** in an episode's context menu.
- **Quality:** always the highest resolution Crunchyroll offers to Kodi.
- **Sign out:** add-on settings → **Sign out**.
- **Something fails:** check the Kodi log for lines starting with `[crunchyrollqr]`.

## How it keeps working

Crunchyroll changes its app credentials from time to time, which is what broke the older Kodi add-ons. This add-on downloads the current ones daily from [crunchy-labs/artifacts](https://github.com/crunchy-labs/artifacts), which updates them automatically, and falls back to a built-in copy.

## Building

Needs only Python 3. In the project folder:

```bash
python build_zip.py
```

This writes `dist/` with two zips and `SHA256SUMS`:

- `plugin.video.crunchyrollqr-<version>.zip`, the add-on. Install it on a Kodi with **Install from zip file** to try it.
- `repository.crunchyrollqr-<version>.zip`, the repository add-on that points Kodi at the update site.

**Versions.** The add-on's version comes from the git tag; `addon.xml` only holds a placeholder.

- `python build_zip.py --tag v1.0.0` builds version `1.0.0`, exactly what the release will contain.
- `python build_zip.py --tag v1.1.0-rc.1` builds the pre-release `1.1.0~rc.1`. Kodi needs the `~` to sort it below `1.1.0`; the tag and the zip's file name never have it.
- Without `--tag` the version comes from git (`1.0.1~dev2` = 2 commits after v1.0.0), or is `0.0.0~dev` without git.

The repository add-on keeps its own version (`repository.crunchyrollqr/addon.xml`, `1.0.0`), raised only when the update site's address changes.

`icon.png` and `license.txt` exist once, next to this readme; the build copies them into both zips.

## Testing

```bash
pip install zxing-cpp pillow
python -m unittest discover -s tests
```

The only test checks that the built-in QR encoder produces codes a real decoder reads back.

## CI and releases

- **CI** (`.github/workflows/ci.yml`), on every push to main and every pull request: compile check, the test, building the zips and Kodi's official add-on checker.
- **Release** (`.github/workflows/release.yml`), on pushing a tag:

  ```bash
  git tag v1.0.0
  git push origin v1.0.0
  ```

  It builds the zips with the tag's version and creates the GitHub release. For a normal release (`vX.Y.Z`) it also rebuilds the Kodi repository site on GitHub Pages (`build_repo.py`), so every Kodi gets the update. A pre-release (`vX.Y.Z-<suffix>`) only becomes a GitHub pre-release.
- **Pulling a broken release:** delete it on GitHub, then Actions → Release → **Run workflow** to rebuild the site without it.
- **One-time setup** of the GitHub repo:
  1. Settings → Pages → Source: **GitHub Actions**.
  2. Settings → Environments → **github-pages** → Deployment branches and tags → add a rule for Ref type **Tag**, pattern `v*`. Without it releases fail at the Pages step.

## License

MIT. Not affiliated with Crunchyroll. Needs a Crunchyroll account; premium content needs a premium subscription.

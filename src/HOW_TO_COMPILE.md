# 999 player source

A Spotify-style Windows desktop player for juicewrldvault.com: glass UI, Apple Music-style synced lyrics,
Discord rich presence, Last.fm scrobbling, downloads, local files.

## requirements

- Windows 10/11, 64-bit
- Python 3.12 or newer from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH" in the installer)

## compile

Open PowerShell in this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The script installs the Python packages (`PySide6`, `requests`, `mutagen`, `pyinstaller`), generates the icon,
runs PyInstaller and prunes unneeded Chromium files. Result: `dist\999player\999player.exe` (~360 MB folder,
the Chromium runtime lives in `_internal` — keep the folder together). First build takes 3–5 minutes.

Manual equivalent:

```powershell
py -m pip install PySide6 requests mutagen pyinstaller
py .\make_icon.py
py -m PyInstaller --noconfirm --onedir --windowed --name "999player" --icon ".\assets\icon.ico" --add-data "ui;ui" --add-data "assets;assets" main.py
```

## installer

After `build_exe.ps1`:

```powershell
py .\make_installer.py
```

zips `dist\999player`, builds a small QtWidgets-only setup exe from `installer.py` and glues the zip onto its end.
Result: `dist\999 player setup.exe` (one file, ~230 MB). It installs to `C:\999player` by default (user-selectable),
adds desktop / start-menu shortcuts and a Programs & Features entry whose uninstall runs `999player.exe --uninstall`
(the glass uninstaller lives inside the app, so `installer.py` changes need both builds). `--skip-zip` reuses the last payload.

Dev preview without building: `py installer.py --payload build\installer\payload.zip --shot out.png --page 1`,
`py installer.py --uninstall-preview --install-dir C:\999player`.

## package

```powershell
py .\package.py
```

fills `C:\Projects\JuicePlayer\` with `app-src.zip`, `installer-src.zip`, `999player-setup.exe` (installer) and `999player-ptb.zip` (portable build).

## release (auto-updates)

The app checks `https://api.github.com/repos/999player/999player/releases/latest` half a minute after launch and every
six hours (`updater.py`). A newer tag (`vX.Y.Z`) with a `999player-setup.exe` asset is downloaded into
`%localappdata%\999player\updates`, checked against github's sha256 digest, and installed the next time the app opens
(or right away from settings → updates → restart to update): the app starts the setup with `--update <install dir>`,
which waits for the app to close, unpacks over the folder, keeps shortcuts and the programs entry as they were, and opens
the app again. Settings → "download updates automatically" turns the background download off (checking stays on).

One command does the whole thing:

```powershell
py .\release.py 2.1.0 --notes "what changed"
```

bumps `version.py` + the exe version resources, runs `build_exe.ps1`, `make_installer.py`, `package.py`, then
`gh release create v2.1.0` with `999player-setup.exe` and `999player-ptb.zip`. Needs `gh auth login` once, and the repo
has to be public for installed apps to download from it. `--draft` publishes a draft (nothing updates until you
press publish on github), `--skip-build` reuses the last build, `--bump-only` just writes the version.

## run from source

```powershell
py -m pip install PySide6 requests mutagen
py main.py
```

Dev flags: `--debug` (console log), `--devtools` (F12 → Chromium devtools), `--selftest` (headless check of catalog + audio engines + lyrics),
`--screenshot out.png --js "app.go({name:'cat', key:'unreleased'})" --delay 2000 --wait 1500 --exit-after`.

## editing

- Everything in `ui\` (html / css / js / covers / fonts) is plain data: after editing, copy `ui\` over `dist\999player\_internal\ui\` and restart — no rebuild.
- `*.py` changes need a rebuild.
- New era covers: drop a folder into your album-covers source dir, add a line to `MAP` in `make_covers.py`, run `py make_covers.py`,
  then add the era to `COVER_KEYWORDS` in `ui\js\util.js` and (for Discord) a public image URL to `ui\covers\discord_art.json`.

## files

| file | role |
|---|---|
| `main.py` | window, embedded browser, command-line flags |
| `bridge.py` | everything the UI asks Python for (downloads, likes, playlists, settings, Discord, Last.fm, local files, accent colour) |
| `catalog.py` | fetches + normalizes the vault's song catalog (public Supabase REST) |
| `scheme.py` | serves the UI, catalog and local files to the browser over the internal `jv://` scheme |
| `native_player.py` | Qt audio fallback for formats Chromium can't decode (m4a) |
| `downloader.py` | downloads + tags audio (title / artist / era / cover) |
| `discord_rpc.py` | Discord rich presence over the local IPC pipe |
| `lastfm.py` | Last.fm auth, now-playing, scrobbling |
| `localfiles.py` | scans local music folders (tags + embedded art) |
| `accent.py` | dominant colour of the current cover → UI accent |
| `lyrics_store.py` | offline lyrics: `.lrc` + `.json` per song in `assets\lyrics` (shipped) and `%LOCALAPPDATA%\999player\lyrics` (user). `py lyrics_store.py` refreshes the shipped set before a build |
| `appdata.py` | app folders, logging, settings + library storage (`%LOCALAPPDATA%\999player`) |
| `installer.py` | glass setup + uninstall windows (QtWidgets, no WebEngine); payload zip is read from the exe itself |
| `make_installer.py` | builds `dist\999 player setup.exe` (zip + stub + glue) |
| `package.py` | copies the deliverables into `C:\Projects\JuicePlayer\` |
| `make_icon.py`, `make_covers.py` | generate the icon / normalize era covers into `ui\covers` |
| `ui\` | the interface: `index.html`, `styles.css`, `js\*.js`, `covers\`, `fonts\` |

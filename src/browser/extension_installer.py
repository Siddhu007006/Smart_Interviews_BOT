"""
Automated Hive Extension Detector installer.

Approach: Direct Profile Injection
------------------------------------
We skip the Chrome Web Store install flow entirely (which requires a signed-in
Google account and shows a native popup that Playwright cannot dismiss).

Instead, we:
  1. Download the .crx from Google's update server.
  2. Unpack the ZIP payload into the bot data directory.
  3. Copy the unpacked extension directly into the Chrome profile's
     Extensions/<id>/<version>/ directory.
  4. Register it in the profile's Preferences JSON file with the correct
     fields Chrome expects for a locally-installed extension.
  5. On the next Chrome launch (with no extra CLI flags needed), Chrome
     automatically loads the extension as if it was normally installed.

This is 100% automatic. No user interaction, no Google account, no popups.

Why this works
--------------
Chrome's extension loader reads two things:
  a) Files at  <profile>/Default/Extensions/<id>/<version>/
  b) A record in <profile>/Default/Preferences  under
     extensions.settings.<id>

We write both. Chrome accepts this as a valid locally-installed extension
(same as "Load unpacked" in developer mode, but permanent).

Note: Chrome will show a one-time "Disable developer mode extensions" infobar
the first time it opens with a manually-injected extension. That bar can be
dismissed by clicking X and does not affect bot operation.
"""

import io
import json
import shutil
import struct
import urllib.request
import zipfile
from pathlib import Path

from src.utils import get_logger, ExtensionError

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Hive Extension Detector constants
# ---------------------------------------------------------------------------
EXTENSION_ID = "goknflnoeiaookhdbnldcbnodjahpgdh"
EXTENSION_NAME = "Hive Extension Detector"
EXTENSION_STORE_URL = (
    "https://chromewebstore.google.com/detail/"
    f"hive-extension-detector/{EXTENSION_ID}"
)

_CRX_URL = (
    "https://clients2.google.com/service/update2/crx"
    "?response=redirect"
    "&prodversion=130.0"
    "&acceptformat=crx2,crx3"
    f"&x=id%3D{EXTENSION_ID}%26uc"
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# CRX3 download + unpack helpers
# ---------------------------------------------------------------------------

def _download_crx() -> bytes:
    """Download the Hive Extension CRX from Google's update server."""
    logger.info(f"Downloading {EXTENSION_NAME} CRX from Google...")
    req = urllib.request.Request(_CRX_URL, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    logger.info(f"CRX downloaded ({len(data):,} bytes)")
    return data


def _unpack_crx3(crx_data: bytes, dest: Path) -> None:
    """
    Extract the ZIP payload from a CRX3 binary into dest/.

    CRX3 layout:
      [0:4]        magic      b"Cr24"
      [4:8]        version    LE uint32  (must be 3)
      [8:12]       hdr_size   LE uint32
      [12:12+n]    protobuf header (ignored)
      [12+n:]      ZIP archive
    """
    magic, version, hdr_size = struct.unpack_from("<4sII", crx_data, 0)
    if magic != b"Cr24":
        raise ExtensionError(f"Not a valid CRX file (magic={magic!r})")
    if version != 3:
        raise ExtensionError(f"Expected CRX3, got version {version}")
    zip_data = crx_data[12 + hdr_size:]
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        zf.extractall(dest)
    logger.debug(f"CRX ZIP extracted to {dest}")


def _read_extension_version(unpack_dir: Path) -> str:
    """Read the version string from the unpacked extension's manifest.json."""
    manifest_path = unpack_dir / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    version = manifest.get("version", "1.0.0")
    logger.debug(f"Extension version: {version}")
    return version


def _sanitize_manifest(manifest_path: Path) -> None:
    """
    Remove update_url from manifest.json and delete _metadata/ if present.

    Chrome refuses to load a developer-mode extension when update_url is set.
    Removing it allows direct profile injection to work.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    changed = "update_url" in manifest
    if changed:
        del manifest["update_url"]
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        logger.debug("Removed update_url from manifest.json")

    metadata_dir = manifest_path.parent / "_metadata"
    if metadata_dir.exists():
        shutil.rmtree(metadata_dir)
        logger.debug("Removed _metadata/ from unpacked extension")


def _load_manifest(ext_dir: Path) -> dict:
    """Load and return the manifest.json as a dict."""
    with open(ext_dir / "manifest.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _inject_into_profile(unpack_dir: Path, profile_path: Path, version: str) -> Path:
    """
    Copy the unpacked extension into the Chrome profile's Extensions directory
    and register it in the profile's Preferences file.

    Args:
        unpack_dir:   Source directory (unpacked CRX files)
        profile_path: Chrome profile root (e.g. ~/.hive_bot_profile)
        version:      Extension version string (e.g. "1.2.0")

    Returns:
        Path to the installed extension directory inside the profile.
    """
    # Copy extension files into profile
    ext_dest = profile_path / "Default" / "Extensions" / EXTENSION_ID / version
    if ext_dest.exists():
        shutil.rmtree(ext_dest)
    shutil.copytree(unpack_dir, ext_dest)
    logger.info(f"Extension files copied to: {ext_dest}")

    # Patch Preferences to register the extension
    prefs_path = profile_path / "Default" / "Preferences"
    if prefs_path.exists():
        with open(prefs_path, "r", encoding="utf-8") as f:
            prefs = json.load(f)
    else:
        prefs = {}

    ext_settings = prefs.setdefault("extensions", {}).setdefault("settings", {})
    ext_settings[EXTENSION_ID] = {
        "active_permissions": {
            "api": ["storage"],
            "explicit_host": [
                "https://hive.smartinterviews.in/*",
                "https://*.smartinterviews.in/*",
            ],
            "manifest_permissions": [],
            "scriptable_host": [
                "https://hive.smartinterviews.in/*",
                "https://*.smartinterviews.in/*",
            ],
        },
        "creation_flags": 9,
        "from_bookmark": False,
        "from_webstore": False,
        "granted_permissions": {
            "api": ["storage"],
            "explicit_host": [
                "https://hive.smartinterviews.in/*",
                "https://*.smartinterviews.in/*",
            ],
            "manifest_permissions": [],
            "scriptable_host": [
                "https://hive.smartinterviews.in/*",
                "https://*.smartinterviews.in/*",
            ],
        },
        "install_time": "13000000000000000",
        "location": 4,
        "manifest": _load_manifest(ext_dest),
        "path": str(ext_dest),
        "state": 1,
        "was_installed_by_default": False,
        "was_installed_by_oem": False,
    }

    with open(prefs_path, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)
    logger.info("Extension registered in Chrome Preferences")

    return ext_dest


# ---------------------------------------------------------------------------
# Main installer class
# ---------------------------------------------------------------------------

class ExtensionInstaller:
    """
    Manages downloading and zero-interaction installation of the Hive Extension
    Detector directly into the Chrome profile.

    Usage inside HiveBot
    --------------------
    installer = ExtensionInstaller(profile_path, data_dir)
    installer.ensure_installed()   # idempotent — fast on second+ runs
    # Launch Chrome normally — extension loads automatically, no extra flags
    """

    def __init__(self, profile_path: Path, data_dir: Path) -> None:
        """
        Args:
            profile_path: Chrome persistent profile dir (e.g. ~/.hive_bot_profile)
            data_dir:     Bot data dir for caching the unpacked CRX (e.g. ~/.hive_bot)
        """
        self.profile_path = profile_path.expanduser().resolve()
        self.data_dir = data_dir.expanduser().resolve()
        self._ext_unpack_dir: Path = self.data_dir / "hive_extension"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_installed_in_profile(self) -> bool:
        """
        True if the extension is already installed in the Chrome profile.

        Chrome stores extension files under:
          <profile>/Default/Extensions/<extension_id>/
        """
        ext_path = self.profile_path / "Default" / "Extensions" / EXTENSION_ID
        return ext_path.exists()

    def ensure_installed(self) -> None:
        """
        Ensure the extension is installed in the profile. Fully automatic.

        Steps:
          1. If already installed -> return immediately (fast path).
          2. Download the CRX from Google (if not already cached locally).
          3. Unpack the CRX ZIP.
          4. Copy files into the profile Extensions directory.
          5. Register in Preferences.

        After this returns, Chrome loads the extension automatically on the
        next launch. No --load-extension flags, no user interaction.

        Raises:
            ExtensionError: If download, unpack, or injection fails.
        """
        if self.is_installed_in_profile():
            logger.debug("Extension already installed in profile — nothing to do.")
            return

        logger.info(f"Installing '{EXTENSION_NAME}' into Chrome profile...")

        unpack_dir = self._ensure_unpacked()
        version = _read_extension_version(unpack_dir)
        _inject_into_profile(unpack_dir, self.profile_path, version)

        logger.info(
            f"✓ '{EXTENSION_NAME}' v{version} installed. "
            "Zero user interaction required."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_unpacked(self) -> Path:
        """
        Download and unpack the CRX if not already cached locally.

        Returns:
            Path to the unpacked extension directory.
        """
        manifest = self._ext_unpack_dir / "manifest.json"
        if manifest.exists():
            logger.debug(f"Using cached CRX: {self._ext_unpack_dir}")
            return self._ext_unpack_dir

        logger.info("Downloading and unpacking CRX...")
        self._ext_unpack_dir.mkdir(parents=True, exist_ok=True)
        crx_data = _download_crx()
        _unpack_crx3(crx_data, self._ext_unpack_dir)
        _sanitize_manifest(manifest)
        logger.info(f"CRX unpacked to: {self._ext_unpack_dir}")
        return self._ext_unpack_dir

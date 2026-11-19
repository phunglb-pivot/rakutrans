"""
Unit tests for update_checker, packaging metadata consistency, and update UI flows.
"""

import ast
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from config import APP_VERSION, RELEASES_PAGE_URL
from update_checker import (
    UpdateCheckResult,
    UpdateInfo,
    check_for_updates,
    is_newer_version,
    normalize_version_str,
    parse_version,
    pick_platform_asset,
)

try:
    import tkinter  # noqa: F401
    import customtkinter as ctk
    HAS_TKINTER = True
except (ImportError, ModuleNotFoundError):
    HAS_TKINTER = False


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self) -> bytes:
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestUpdateChecker(unittest.TestCase):

    def test_version_parsing_and_comparison(self):
        self.assertEqual(normalize_version_str(" v1.2.3 "), "1.2.3")
        self.assertEqual(parse_version("v1.2.3")[0], (1, 2, 3))

        self.assertTrue(is_newer_version("1.0.1", "1.0.0"))
        self.assertTrue(is_newer_version("v1.0.10", "1.0.2"))
        self.assertTrue(is_newer_version("2.0.0", "1.9.9"))
        self.assertFalse(is_newer_version("1.0.0", "v1.0.0"))
        self.assertFalse(is_newer_version("1.0", "1.0.0"))
        self.assertFalse(is_newer_version("0.9.9", "1.0.0"))

        # Pre-release handling
        self.assertTrue(is_newer_version("1.1.0", "1.1.0-beta.1"))
        self.assertFalse(is_newer_version("1.1.0-beta.1", "1.1.0"))
        self.assertTrue(is_newer_version("1.1.0-beta.10", "1.1.0-beta.2"))
        self.assertTrue(is_newer_version("1.1.0-rc.1", "1.1.0-beta.9"))

    def test_pick_platform_asset_matches_os_and_rejects_insecure_urls(self):
        assets = [
            {"name": "RakuTrans-Installer-macOS.dmg", "browser_download_url": "https://github.com/org/repo/releases/download/v1.1.0/RakuTrans-Installer-macOS.dmg"},
            {"name": "RakuTrans-Installer-Windows.exe", "browser_download_url": "https://github.com/org/repo/releases/download/v1.1.0/RakuTrans-Installer-Windows.exe"},
            {"name": "insecure.dmg", "browser_download_url": "http://example.com/insecure.dmg"},
        ]

        mac_url, mac_name = pick_platform_asset(assets, system_name="Darwin")
        self.assertEqual(mac_name, "RakuTrans-Installer-macOS.dmg")
        self.assertTrue(mac_url.startswith("https://"))

        win_url, win_name = pick_platform_asset(assets, system_name="Windows")
        self.assertEqual(win_name, "RakuTrans-Installer-Windows.exe")
        self.assertTrue(win_url.startswith("https://"))

        insecure_only = [{"name": "app.dmg", "browser_download_url": "http://example.com/app.dmg"}]
        self.assertEqual(pick_platform_asset(insecure_only, system_name="Darwin"), ("", ""))

    def test_check_for_updates_responses(self):
        # 1. Newer release available
        payload_new = {
            "tag_name": "v1.2.0",
            "html_url": "https://github.com/phunglb-pivot/rakutrans/releases/tag/v1.2.0",
            "body": "- Faster PDF translation\n- Bug fixes",
            "published_at": "2026-11-20T00:00:00Z",
            "assets": [
                {
                    "name": "RakuTrans-Installer-macOS.dmg",
                    "browser_download_url": "https://github.com/phunglb-pivot/rakutrans/releases/download/v1.2.0/RakuTrans-Installer-macOS.dmg",
                },
                {
                    "name": "RakuTrans-Installer-Windows.exe",
                    "browser_download_url": "https://github.com/phunglb-pivot/rakutrans/releases/download/v1.2.0/RakuTrans-Installer-Windows.exe",
                },
            ],
        }
        res_mac = check_for_updates(
            current_version="1.0.0",
            system_name="Darwin",
            opener=lambda req, timeout=6.0: _FakeHTTPResponse(payload_new),
        )
        self.assertEqual(res_mac.status, "update_available")
        self.assertIsNotNone(res_mac.info)
        self.assertEqual(res_mac.info.latest_version, "1.2.0")
        self.assertTrue(res_mac.info.download_url.endswith(".dmg"))
        self.assertIn("Faster PDF translation", res_mac.info.release_notes)

        # 2. Already on latest version
        res_same = check_for_updates(
            current_version="1.2.0",
            system_name="Windows",
            opener=lambda req, timeout=6.0: _FakeHTTPResponse(payload_new),
        )
        self.assertEqual(res_same.status, "up_to_date")
        self.assertFalse(res_same.info.has_update)

        # 3. 404 (no releases published yet) treated cleanly as up_to_date
        def raise_404(req, timeout=6.0):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", hdrs=None, fp=None)

        res_404 = check_for_updates(current_version="1.0.0", opener=raise_404)
        self.assertEqual(res_404.status, "up_to_date")
        self.assertEqual(res_404.info.release_url, RELEASES_PAGE_URL)

        # 4. 403 rate limit returns error
        def raise_403(req, timeout=6.0):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", hdrs=None, fp=None)

        res_403 = check_for_updates(current_version="1.0.0", opener=raise_403)
        self.assertEqual(res_403.status, "error")
        self.assertIn("403", res_403.error_message)

        # 5. Network failure returns error
        def raise_net(req, timeout=6.0):
            raise OSError("Network unreachable")

        res_err = check_for_updates(current_version="1.0.0", opener=raise_net)
        self.assertEqual(res_err.status, "error")
        self.assertIn("Network unreachable", res_err.error_message)

    def test_packaging_configs_and_release_workflow_integrity(self):
        root = Path(__file__).resolve().parent.parent

        # 1. Inno Setup keeps fixed AppId and cleans stale _internal on upgrade
        iss_text = (root / "installer_windows.iss").read_text(encoding="utf-8")
        self.assertIn("AppId={{8D4F2E1A-9C3B-4B7E-A21D-6F0C5E8A1B42}", iss_text)
        self.assertIn("[InstallDelete]", iss_text)
        self.assertIn('Name: "{app}\\_internal"', iss_text)

        # 2. PyInstaller spec syncs config metadata, Info.plist fields, and covers requirements.txt packages
        from config import APP_BUNDLE_ID, APP_EXECUTABLE_NAME, APP_NAME

        spec_text = (root / "RakuTrans.spec").read_text(encoding="utf-8")
        ast.parse(spec_text)  # Must remain valid Python syntax
        self.assertIn("APP_EXECUTABLE_NAME", spec_text)
        self.assertIn("APP_BUNDLE_ID", spec_text)
        self.assertIn("CFBundleShortVersionString", spec_text)
        self.assertIn("CFBundleVersion", spec_text)
        self.assertIn("NSHighResolutionCapable", spec_text)
        cfg_text = (root / "config.py").read_text(encoding="utf-8")
        self.assertIn(APP_VERSION, cfg_text)
        self.assertIn(APP_NAME, cfg_text)
        self.assertIn(APP_EXECUTABLE_NAME, cfg_text)
        self.assertIn(APP_BUNDLE_ID, cfg_text)

        req_pkg_to_spec_token = {
            "customtkinter": "customtkinter",
            "tkinterdnd2": "tkinterdnd2",
            "pillow": "PIL",
            "openpyxl": "openpyxl",
            "markitdown": "markitdown",
            "python-docx": "docx",
            "python-pptx": "pptx",
            "pymupdf": "pymupdf",
            "pdf2docx": "pdf2docx",
            "pypdf": "pypdf",
            "reportlab": "reportlab",
            "google-genai": "google.genai",
            "openai": "openai",
            "anthropic": "anthropic",
        }
        req_lines = [
            line.split(">=")[0].split("==")[0].strip().lower()
            for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for req_pkg in req_lines:
            self.assertIn(req_pkg, req_pkg_to_spec_token)
            self.assertIn(req_pkg_to_spec_token[req_pkg], spec_text)

        # 3. GitHub Actions release workflow exists and references real build artifacts
        wf_path = root / ".github" / "workflows" / "release.yml"
        self.assertTrue(wf_path.exists())
        wf_text = wf_path.read_text(encoding="utf-8")
        self.assertIn("RakuTrans-Installer-macOS.dmg", wf_text)
        self.assertIn("RakuTrans-Installer-Windows.exe", wf_text)
        self.assertIn("build_macos.sh", wf_text)
        self.assertIn("build_windows.bat", wf_text)


@unittest.skipUnless(HAS_TKINTER, "Tkinter is not available in this Python environment")
class TestUpdateUI(unittest.TestCase):

    def test_settings_update_check_and_update_modal(self):
        import config as config_mod
        import model_fetcher
        from config import AppConfig
        from components.settings_modal import SettingsView
        from components.update_modal import UpdateModal

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch.object(config_mod, "CONFIG_DIR", tmp_path), \
                 patch.object(config_mod, "CONFIG_FILE", tmp_path / "config.json"), \
                 patch.object(model_fetcher, "CACHE_DIR", tmp_path), \
                 patch.object(model_fetcher, "MODELS_CACHE_FILE", tmp_path / "models_cache.json"):
                cfg = AppConfig()
                found_events = []
                root = ctk.CTk()

                def _cleanup_root():
                    try:
                        if root.winfo_exists():
                            root.destroy()
                    except Exception:
                        pass

                self.addCleanup(_cleanup_root)
                sv = SettingsView(
                    root,
                    config=cfg,
                    get_translation=lambda k, **kw: k if not kw else f"{k}:{kw}",
                    on_save_callback=lambda c: None,
                    on_close_callback=lambda: None,
                    on_update_found=lambda info: found_events.append(info),
                )
                root.update()

                info = UpdateInfo(
                    current_version="1.0.0",
                    latest_version="1.1.0",
                    has_update=True,
                    release_url="https://github.com/phunglb-pivot/rakutrans/releases/tag/v1.1.0",
                    download_url="https://github.com/phunglb-pivot/rakutrans/releases/download/v1.1.0/RakuTrans-Installer-macOS.dmg",
                    asset_name="RakuTrans-Installer-macOS.dmg",
                    release_notes="New features",
                )

                def fake_async(cb, **kwargs):
                    cb(UpdateCheckResult(status="update_available", info=info))

                with patch("components.settings_modal.check_for_updates_async", side_effect=fake_async):
                    sv._check_for_updates()
                    root.update()

                self.assertEqual(len(found_events), 1)
                self.assertEqual(sv._update_status_state, "update_available")
                self.assertEqual(sv.download_update_btn.winfo_manager(), "pack")

                # UpdateModal skip & download callbacks
                skipped = []
                modal = UpdateModal(
                    root,
                    update_info=info,
                    on_skip_version=lambda v: skipped.append(v),
                    get_translation=lambda k, **kw: k,
                )
                modal.update()
                modal._handle_skip()
                self.assertEqual(skipped, ["1.1.0"])
                self.assertTrue(modal._closed)

                # Toggle auto-check preference persists
                sv.auto_update_var.set(False)
                sv._on_auto_update_toggled()
                self.assertFalse(AppConfig.load().auto_check_updates)

                sv.destroy()
                root.destroy()


if __name__ == "__main__":
    unittest.main()

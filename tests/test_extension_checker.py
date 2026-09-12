import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from src.browser.extension import ExtensionChecker, EXTENSION_ID
from src.utils.errors import ExtensionError

@pytest.fixture
def mock_page_with_context():
    page = AsyncMock()
    context = MagicMock()
    context.service_workers = []
    context.background_pages = []
    page.context = context
    page.evaluate = AsyncMock(return_value="")
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
    locator.first = MagicMock()
    locator.first.is_visible = AsyncMock(return_value=False)
    page.locator = MagicMock(return_value=locator)
    return page

def test_tier1_profile_check(temp_dir, mock_page_with_context):
    checker = ExtensionChecker(mock_page_with_context, profile_path=temp_dir)
    assert checker.verify_profile_installation() is False

    ext_dir = temp_dir / "Default" / "Extensions" / EXTENSION_ID / "1.2"
    ext_dir.mkdir(parents=True, exist_ok=True)
    dummy_file = ext_dir / "manifest.json"
    dummy_file.write_text("{}", encoding="utf-8")

    assert checker.verify_profile_installation() is True

@pytest.mark.asyncio
async def test_tier2_runtime_check(mock_page_with_context):
    checker = ExtensionChecker(mock_page_with_context)
    assert await checker.verify_runtime_active(retries=1, retry_delay_s=0.01) is False

    sw = MagicMock()
    sw.url = f"chrome-extension://{EXTENSION_ID}/background.js"
    mock_page_with_context.context.service_workers = [sw]

    assert await checker.verify_runtime_active(retries=1, retry_delay_s=0.01) is True

@pytest.mark.asyncio
async def test_tier3_blocker_dismissed(mock_page_with_context):
    checker = ExtensionChecker(mock_page_with_context)
    # Absent blocker
    assert await checker.verify_hive_blocker_dismissed(timeout_s=0.1) is True

    # Present and visible blocker
    locator = MagicMock()
    locator.count = AsyncMock(return_value=1)
    locator.first = MagicMock()
    locator.first.is_visible = AsyncMock(return_value=True)
    mock_page_with_context.locator = MagicMock(return_value=locator)

    assert await checker.verify_hive_blocker_dismissed(timeout_s=0.2) is False

@pytest.mark.asyncio
async def test_verify_extension_ready_full_flow(temp_dir, mock_page_with_context):
    ext_dir = temp_dir / "Default" / "Extensions" / EXTENSION_ID / "1.2"
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / "manifest.json").write_text("{}", encoding="utf-8")

    sw = MagicMock()
    sw.url = f"chrome-extension://{EXTENSION_ID}/background.js"
    mock_page_with_context.context.service_workers = [sw]

    checker = ExtensionChecker(mock_page_with_context, profile_path=temp_dir)
    assert await checker.verify_extension_ready(timeout_s=0.1) is True

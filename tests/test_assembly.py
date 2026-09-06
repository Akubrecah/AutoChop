"""
Unit tests for Module 3: Assembly & Stitching
Verifies edit manifest generation, table structure, and take metadata tabulation.
"""

from pathlib import Path
from autochop.core.assembly import generate_edit_manifest


def test_generate_edit_manifest(tmp_path: Path):
    """
    Tests Markdown manifest generation from takes metadata.
    """
    takes_meta = [
        {
            "index": 1,
            "filename": "take_001.mp4",
            "start": 0.5,
            "end": 4.2,
            "size_bytes": 1024 * 1024 * 2,  # 2MB
            "transcript_preview": "Welcome to this complete guide on editing videos faster.",
        },
        {
            "index": 2,
            "filename": "take_002.mp4",
            "start": 5.0,
            "end": 8.5,
            "size_bytes": 1024 * 512,  # 512KB
            "transcript_preview": "Here is how you cut dead air automatically.",
        },
    ]

    manifest_file = tmp_path / "manifest.md"
    manifest_md = generate_edit_manifest(takes_meta, output_markdown_path=manifest_file)

    assert manifest_file.exists()
    assert "# 🎬 AutoChop Edit Manifest" in manifest_md
    assert "Take 01" in manifest_md
    assert "`take_001.mp4`" in manifest_md
    assert "0.50s – 4.20s" in manifest_md
    assert "Take 02" in manifest_md
    assert "`take_002.mp4`" in manifest_md
    assert "**Total Assembled Cuts:** 2 takes" in manifest_md

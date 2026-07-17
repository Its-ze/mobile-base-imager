import gzip
import lzma
import zipfile
from pathlib import Path

import pytest
import zstandard

from app import core
from app.core import (
    Disk,
    decompressed_name,
    filter_safe_disks,
    format_disk,
    human_size,
    image_format,
    is_safe_target,
    is_supported_image,
    prepare_image,
    sha256_file,
    write_checksum,
)


def disk(**overrides):
    values = dict(
        number=3,
        name="SD Reader",
        size=64_000_000_000,
        bus_type=12,
        bus_name="SD",
        media_type="Removable Media",
        pnp_id="SD\\CARD",
        is_boot=False,
        is_system=False,
        is_offline=False,
        operational_status="OK",
    )
    values.update(overrides)
    return Disk(**values)


def progress(_stage: str, _done: int, _total: int) -> None:
    pass


def test_system_disk_is_always_blocked():
    assert not is_safe_target(disk(is_system=True))
    assert not is_safe_target(disk(is_boot=True))


def test_only_removable_usb_or_sd_is_allowed():
    assert is_safe_target(disk())
    assert is_safe_target(disk(bus_type=7, bus_name="USB", pnp_id="USBSTOR\\DISK"))
    assert not is_safe_target(disk(bus_type=11, bus_name="SATA", media_type="Fixed hard disk media"))
    assert not is_safe_target(disk(bus_type=7, bus_name="USB", media_type="Fixed", pnp_id="USB\\VID"))


def test_safe_disk_list_is_sorted_and_filtered():
    result = filter_safe_disks([disk(number=9), disk(number=1), disk(number=0, is_system=True)])
    assert [item.number for item in result] == [1, 9]


def test_hash_human_size_and_checksum_sidecar(tmp_path: Path):
    target = tmp_path / "sample.img"
    target.write_bytes(b"mobile-base")
    digest = sha256_file(target)
    assert digest == "B0A6F8A8B974BDA19EE4F90300C4CF3BF4736557A5F0004518E18D793C5D2468"
    assert human_size(64_000_000_000) == "64.0 GB"
    checksum = write_checksum(target, digest)
    assert checksum.read_text(encoding="utf-8") == f"{digest.lower()}  sample.img\n"


@pytest.mark.parametrize(
    ("filename", "label"),
    [
        ("field.img", "Raw image"),
        ("field.img.zst", "Zstandard image"),
        ("field.img.gz", "Gzip image"),
        ("field.img.xz", "XZ image"),
        ("field.zip", "ZIP image"),
    ],
)
def test_supported_image_catalog(filename: str, label: str):
    assert is_supported_image(filename)
    assert image_format(filename) == label
    assert not is_supported_image("installer.iso")


def test_prepare_all_compressed_formats(tmp_path: Path):
    payload = (b"mobile-base-full-image\0" * 2048) + b"end"
    cache = tmp_path / "cache"
    raw = tmp_path / "field.img"
    raw.write_bytes(payload)

    zst = tmp_path / "zstd.img.zst"
    zst.write_bytes(zstandard.ZstdCompressor().compress(payload))
    gz = tmp_path / "gzip.img.gz"
    with gzip.open(gz, "wb") as output:
        output.write(payload)
    xz = tmp_path / "xz.img.xz"
    with lzma.open(xz, "wb") as output:
        output.write(payload)
    zipped = tmp_path / "archive.zip"
    with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("folder/zip.img", payload)

    assert prepare_image(raw, cache, progress) == raw
    for source in (zst, gz, xz, zipped):
        prepared = prepare_image(source, cache, progress)
        assert prepared.read_bytes() == payload
        assert prepared.suffix == ".img"


def test_zip_requires_exactly_one_image(tmp_path: Path):
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one.img", b"one")
        archive.writestr("two.img", b"two")
    with pytest.raises(ValueError, match="exactly one"):
        decompressed_name(archive_path)


def test_format_rejects_large_fat32_before_diskpart(monkeypatch):
    called = False

    def fake_diskpart(_lines):
        nonlocal called
        called = True

    monkeypatch.setattr(core, "run_diskpart", fake_diskpart)
    with pytest.raises(ValueError, match="larger than 32 GB"):
        format_disk(disk(size=64_000_000_000), "fat32")
    assert not called


def test_format_sanitizes_label(monkeypatch):
    captured = []
    monkeypatch.setattr(core, "run_diskpart", lambda lines: captured.extend(lines))
    format_disk(disk(size=16_000_000_000), "fat32", "Mobile Base!!!")
    assert 'format fs=fat32 quick label="MOBILE BASE"' in captured


def test_flash_refuses_image_stored_on_target(tmp_path: Path, monkeypatch):
    image = tmp_path / "source.img"
    image.write_bytes(b"image")
    monkeypatch.setattr(core, "disk_number_for_path", lambda _path: 3)
    monkeypatch.setattr(core, "clean_disk", lambda _disk: pytest.fail("disk must not be cleaned"))
    with pytest.raises(RuntimeError, match="source image is stored on the selected target"):
        core.flash_and_verify(image, disk(number=3), progress)


def test_backup_refuses_destination_on_source_disk(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(core, "disk_number_for_path", lambda _path: 3)
    monkeypatch.setattr(core, "_open_physical_drive", lambda *_args, **_kwargs: pytest.fail("disk must not be opened"))
    with pytest.raises(RuntimeError, match="backup destination is on the source disk"):
        core.backup_disk(disk(number=3), tmp_path / "backup.img.zst", progress)

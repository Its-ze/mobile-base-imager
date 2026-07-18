import gzip
import lzma
import os
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
    if os.name != "nt":
        pytest.skip("Windows-specific FAT32 policy")
    called = False

    def fake_diskpart(_lines):
        nonlocal called
        called = True

    monkeypatch.setattr(core, "run_diskpart", fake_diskpart)
    with pytest.raises(ValueError, match="larger than 32 GB"):
        format_disk(disk(size=64_000_000_000), "fat32")
    assert not called


def test_format_sanitizes_label(monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows DiskPart command test")
    captured = []
    monkeypatch.setattr(core, "run_diskpart", lambda lines: captured.extend(lines))
    format_disk(disk(size=16_000_000_000), "fat32", "Mobile Base!!!")
    assert 'format fs=fat32 quick label="MOBILE BASE"' in captured


def test_windows_raw_flash_clean_removes_existing_partitions(monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows DiskPart raw-write protection")
    captured = []
    monkeypatch.setattr(core, "run_diskpart", lambda lines: captured.extend(lines))
    core.clean_disk(disk(bus_type=7, bus_name="USB", pnp_id="USBSTOR\\DISK"))
    assert captured == ["select disk 3", "attributes disk clear readonly", "clean", "exit"]


def test_diskpart_surfaces_virtual_disk_service_errors(monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows DiskPart error handling")
    result = type("Result", (), {"returncode": 0, "stdout": "Virtual Disk Service error: operation failed", "stderr": ""})()
    monkeypatch.setattr(core.subprocess, "run", lambda *_args, **_kwargs: result)
    with pytest.raises(RuntimeError, match="Virtual Disk Service error"):
        core.run_diskpart(["list disk", "exit"])


def test_flash_writes_partition_header_last(tmp_path: Path, monkeypatch):
    image = tmp_path / "source.img"
    image.write_bytes(b"HEADpayload")
    target = disk(bus_type=7, bus_name="USB", pnp_id="USBSTOR\\DISK")
    cursor = 0
    writes = []
    handle = object()

    def seek(_handle, offset):
        nonlocal cursor
        cursor = offset

    def write(_handle, payload):
        nonlocal cursor
        writes.append((cursor, payload))
        cursor += len(payload)

    monkeypatch.setattr(core, "CHUNK_SIZE", 4)
    monkeypatch.setattr(core, "path_is_on_disk", lambda *_args: False)
    monkeypatch.setattr(core, "clean_disk", lambda _disk: None)
    monkeypatch.setattr(core, "_open_physical_drive", lambda *_args, **_kwargs: handle)
    monkeypatch.setattr(core, "_seek_handle", seek)
    monkeypatch.setattr(core, "_seek_handle_start", lambda item: seek(item, 0))
    monkeypatch.setattr(core, "_write_handle", write)
    monkeypatch.setattr(core, "_flush_handle", lambda _handle: None)
    monkeypatch.setattr(core, "_close_handle", lambda _handle: None)
    digest = core.flash_and_verify(image, target, progress, verify=False)
    assert digest == sha256_file(image)
    assert writes == [(4, b"payl"), (8, b"oad"), (0, b"HEAD")]


def test_flash_refuses_image_stored_on_target(tmp_path: Path, monkeypatch):
    image = tmp_path / "source.img"
    image.write_bytes(b"image")
    target = disk(number=3, path="/dev/sdb")
    monkeypatch.setattr(core, "disk_number_for_path", lambda _path: target.number if os.name == "nt" else target.device_path)
    monkeypatch.setattr(core, "clean_disk", lambda _disk: pytest.fail("disk must not be cleaned"))
    with pytest.raises(RuntimeError, match="source image is stored on the selected target"):
        core.flash_and_verify(image, target, progress)


def test_backup_refuses_destination_on_source_disk(tmp_path: Path, monkeypatch):
    target = disk(number=3, path="/dev/sdb")
    monkeypatch.setattr(core, "disk_number_for_path", lambda _path: target.number if os.name == "nt" else target.device_path)
    monkeypatch.setattr(core, "_open_physical_drive", lambda *_args, **_kwargs: pytest.fail("disk must not be opened"))
    with pytest.raises(RuntimeError, match="backup destination is on the source disk"):
        core.backup_disk(target, tmp_path / "backup.img.zst", progress)


def test_linux_lsblk_filters_internal_and_system_media():
    payload = {
        "blockdevices": [
            {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": 1_000_000, "type": "disk", "model": "Internal", "tran": "nvme", "rm": 0, "hotplug": 0, "ro": 0, "mountpoints": [None], "children": [{"mountpoints": ["/"]}]},
            {"name": "sdb", "path": "/dev/sdb", "size": 64_000_000_000, "type": "disk", "model": "Card Reader", "tran": "usb", "rm": 1, "hotplug": 1, "ro": 0, "mountpoints": [None], "children": [{"mountpoints": ["/media/card"]}]},
            {"name": "sdc", "path": "/dev/sdc", "size": 32_000_000_000, "type": "disk", "model": "USB Boot", "tran": "usb", "rm": 1, "hotplug": 1, "ro": 0, "mountpoints": [None], "children": [{"mountpoints": ["/"]}]},
            {"name": "mmcblk0", "path": "/dev/mmcblk0", "size": 128_000_000_000, "type": "disk", "model": "SD Card", "tran": None, "rm": 0, "hotplug": 1, "ro": 0, "mountpoints": [None]},
            {"name": "mmcblk1", "path": "/dev/mmcblk1", "size": 256_000_000_000, "type": "disk", "model": "Internal eMMC", "tran": None, "rm": 0, "hotplug": 0, "ro": 0, "mountpoints": [None]},
        ]
    }
    result = core.linux_disks_from_lsblk(payload)
    assert [item.device_path for item in result] == ["/dev/sdb", "/dev/mmcblk0"]
    assert result[0].confirmation_text in {"ERASE DISK 1", "ERASE /DEV/SDB"}


@pytest.mark.skipif(os.name == "nt", reason="Linux backend test")
def test_linux_format_command_sequence(monkeypatch):
    target = disk(number=1, size=16_000_000_000, path="/dev/sdb")
    commands = []
    unmounted = []
    monkeypatch.setattr(core, "unmount_linux_disk", lambda item: unmounted.append(item.device_path))
    monkeypatch.setattr(core, "run_linux_command", lambda arguments, timeout=300: commands.append(arguments) or "")
    monkeypatch.setattr(core, "linux_partitions", lambda _item: ["/dev/sdb1"])
    monkeypatch.setattr(core.subprocess, "run", lambda *_args, **_kwargs: type("Result", (), {"returncode": 0})())
    core.format_disk(target, "exfat", "FIELD CARD")
    assert unmounted == ["/dev/sdb"]
    assert ["wipefs", "--all", "/dev/sdb"] in commands
    assert ["parted", "--script", "/dev/sdb", "mklabel", "msdos", "mkpart", "primary", "1MiB", "100%"] in commands
    assert ["mkfs.exfat", "-n", "FIELD CARD", "/dev/sdb1"] in commands


@pytest.mark.skipif(os.name == "nt", reason="Linux raw-device backend test")
def test_linux_raw_flash_verify_and_backup(tmp_path: Path, monkeypatch):
    payload = b"mobile-base-linux-image" * 128
    image = tmp_path / "source.img"
    image.write_bytes(payload)
    device = tmp_path / "device.bin"
    device.write_bytes(b"\0" * (len(payload) + 4096))
    target = disk(number=1, size=device.stat().st_size, path=str(device))
    monkeypatch.setattr(core, "clean_disk", lambda _disk: None)
    monkeypatch.setattr(core, "path_is_on_disk", lambda _path, _disk: False)
    digest = core.flash_and_verify(image, target, progress, verify=True)
    assert digest == sha256_file(image)
    assert device.read_bytes()[: len(payload)] == payload
    backup = core.backup_disk(target, tmp_path / "backup.img.zst", progress, compress=True)
    assert backup.path.exists()
    restored = zstandard.ZstdDecompressor().decompress(backup.path.read_bytes(), max_output_size=target.size)
    assert restored == device.read_bytes()

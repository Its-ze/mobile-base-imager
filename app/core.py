from __future__ import annotations

import ctypes
import gzip
import hashlib
import json
import lzma
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

import zstandard


CHUNK_SIZE = 4 * 1024 * 1024
MAX_TARGET_BYTES = 2 * 1024**4
SAFE_BUS_TYPES = {7, 12}  # USB and SD
SUPPORTED_IMAGE_SUFFIXES = (".img", ".img.zst", ".img.gz", ".img.xz", ".zip")
Progress = Callable[[str, int, int], None]


@dataclass(frozen=True)
class Disk:
    number: int
    name: str
    size: int
    bus_type: int
    bus_name: str
    media_type: str
    pnp_id: str
    is_boot: bool
    is_system: bool
    is_offline: bool
    operational_status: str
    path: str = ""

    @property
    def device_path(self) -> str:
        return self.path or rf"\\.\PhysicalDrive{self.number}"

    @property
    def identifier(self) -> str:
        return f"Disk {self.number}" if os.name == "nt" else self.device_path

    @property
    def confirmation_text(self) -> str:
        return f"ERASE DISK {self.number}" if os.name == "nt" else f"ERASE {self.device_path.upper()}"

    @property
    def size_label(self) -> str:
        return human_size(self.size)

    @property
    def display(self) -> str:
        return f"{self.identifier}  |  {self.name}  |  {self.size_label}  |  {self.bus_name}"


@dataclass(frozen=True)
class BackupResult:
    path: Path
    sha256: str
    bytes_read: int
    compressed: bool


def human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1000
    return f"{size:.1f} TB"


def is_supported_image(path: Path | str) -> bool:
    name = str(path).lower()
    return any(name.endswith(suffix) for suffix in SUPPORTED_IMAGE_SUFFIXES)


def image_format(path: Path | str) -> str:
    name = str(path).lower()
    for suffix, label in (
        (".img.zst", "Zstandard image"),
        (".img.gz", "Gzip image"),
        (".img.xz", "XZ image"),
        (".zip", "ZIP image"),
        (".img", "Raw image"),
    ):
        if name.endswith(suffix):
            return label
    return "Unsupported"


def disk_from_record(record: dict) -> Disk:
    return Disk(
        number=int(record.get("Number", -1)),
        name=str(record.get("FriendlyName") or record.get("Model") or "Unknown device").strip(),
        size=int(record.get("Size") or 0),
        bus_type=int(record.get("BusType") or 0),
        bus_name=str(record.get("BusName") or "Unknown"),
        media_type=str(record.get("MediaType") or ""),
        pnp_id=str(record.get("PnpId") or ""),
        is_boot=bool(record.get("IsBoot")),
        is_system=bool(record.get("IsSystem")),
        is_offline=bool(record.get("IsOffline")),
        operational_status=str(record.get("OperationalStatus") or ""),
    )


def is_safe_target(disk: Disk) -> bool:
    if disk.number < 0 or disk.size <= 0 or disk.size > MAX_TARGET_BYTES:
        return False
    if disk.is_boot or disk.is_system:
        return False
    if disk.bus_type not in SAFE_BUS_TYPES:
        return False
    identity = f"{disk.media_type} {disk.pnp_id} {disk.bus_name}".upper()
    return disk.bus_type == 12 or "REMOVABLE" in identity or "USBSTOR" in identity or " SD" in f" {identity}"


def filter_safe_disks(disks: Iterable[Disk]) -> list[Disk]:
    return sorted((disk for disk in disks if is_safe_target(disk)), key=lambda disk: disk.number)


POWERSHELL_DISKS = r"""
$storage = @(Get-CimInstance -Namespace root/Microsoft/Windows/Storage -ClassName MSFT_Disk)
$legacy = @(Get-CimInstance Win32_DiskDrive)
$rows = foreach ($disk in $storage) {
  $old = $legacy | Where-Object { $_.Index -eq $disk.Number } | Select-Object -First 1
  [pscustomobject]@{
    Number = [int]$disk.Number
    FriendlyName = [string]$disk.FriendlyName
    Model = [string]$old.Model
    Size = [uint64]$disk.Size
    BusType = [int]$disk.BusType
    BusName = switch ([int]$disk.BusType) { 7 {'USB'} 12 {'SD'} default {[string]$disk.BusType} }
    MediaType = [string]$old.MediaType
    PnpId = [string]$old.PNPDeviceID
    IsBoot = [bool]$disk.IsBoot
    IsSystem = [bool]$disk.IsSystem
    IsOffline = [bool]$disk.IsOffline
    OperationalStatus = [string]($disk.OperationalStatus -join ',')
  }
}
@($rows) | ConvertTo-Json -Compress
"""


def enumerate_disks() -> list[Disk]:
    if os.name != "nt":
        return enumerate_linux_disks()
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", POWERSHELL_DISKS],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Windows disk inventory failed")
    payload = completed.stdout.strip().lstrip("\ufeff")
    records = json.loads(payload or "[]")
    if isinstance(records, dict):
        records = [records]
    return filter_safe_disks(disk_from_record(record) for record in records)


def _linux_mounts(node: dict) -> list[str]:
    mounts = [str(item) for item in (node.get("mountpoints") or []) if item]
    for child in node.get("children") or []:
        mounts.extend(_linux_mounts(child))
    return mounts


def linux_disks_from_lsblk(payload: dict) -> list[Disk]:
    disks: list[Disk] = []
    for index, node in enumerate(payload.get("blockdevices") or []):
        if node.get("type") != "disk":
            continue
        path = str(node.get("path") or f"/dev/{node.get('name', '')}")
        transport = str(node.get("tran") or "").lower()
        is_mmc = Path(path).name.startswith("mmcblk")
        mounts = _linux_mounts(node)
        removable = bool(int(node.get("rm") or 0) or int(node.get("hotplug") or 0))
        bus_type = 12 if removable and (is_mmc or transport == "mmc") else (7 if transport == "usb" else 0)
        disks.append(Disk(
            number=index,
            name=str(node.get("model") or Path(path).name).strip(),
            size=int(node.get("size") or 0),
            bus_type=bus_type,
            bus_name="SD" if bus_type == 12 else ("USB" if bus_type == 7 else transport.upper() or "Unknown"),
            media_type="Removable Media" if removable else "Fixed Media",
            pnp_id=f"LINUX:{path}:{transport}:{'RM' if removable else 'FIXED'}",
            is_boot=any(mount in {"/boot", "/boot/efi"} for mount in mounts),
            is_system="/" in mounts,
            is_offline=False,
            operational_status="read-only" if bool(int(node.get("ro") or 0)) else "OK",
            path=path,
        ))
    return filter_safe_disks(disks)


def enumerate_linux_disks() -> list[Disk]:
    completed = subprocess.run(
        ["lsblk", "--json", "--bytes", "--output", "NAME,PATH,SIZE,TYPE,MODEL,TRAN,RM,HOTPLUG,RO,MOUNTPOINTS"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Linux disk inventory failed")
    return linux_disks_from_lsblk(json.loads(completed.stdout))


def disk_number_for_path(path: Path) -> int | str | None:
    """Return the Windows physical disk number containing a local path."""
    if os.name != "nt":
        completed = subprocess.run(
            ["findmnt", "--noheadings", "--output", "SOURCE", "--target", str(path.resolve(strict=False))],
            capture_output=True,
            text=True,
            timeout=15,
        )
        source = completed.stdout.strip().splitlines()[0] if completed.returncode == 0 and completed.stdout.strip() else ""
        if not source.startswith("/dev/"):
            return None
        parent = subprocess.run(["lsblk", "--noheadings", "--output", "PKNAME", source], capture_output=True, text=True, timeout=15).stdout.strip()
        return f"/dev/{parent}" if parent else source
    resolved = path.resolve(strict=False)
    drive = resolved.drive
    if len(drive) < 1 or not drive[0].isalpha():
        return None
    script = f"$p=Get-Partition -DriveLetter '{drive[0]}' -ErrorAction SilentlyContinue | Select-Object -First 1; if($p){{$p.DiskNumber}}"
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    value = completed.stdout.strip()
    return int(value) if completed.returncode == 0 and value.isdigit() else None


def path_is_on_disk(path: Path, disk: Disk) -> bool:
    owner = disk_number_for_path(path)
    return owner == (disk.number if os.name == "nt" else disk.device_path)


def sha256_file(path: Path, progress: Progress | None = None, stage: str = "VERIFYING IMAGE") -> str:
    digest = hashlib.sha256()
    total = path.stat().st_size
    done = 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(stage, done, total)
    return digest.hexdigest().upper()


def write_checksum(path: Path, digest: str) -> Path:
    checksum_path = Path(str(path) + ".sha256")
    checksum_path.write_text(f"{digest.lower()}  {path.name}\n", encoding="utf-8")
    return checksum_path


def download_file(url: str, destination: Path, expected_sha256: str | None, progress: Progress) -> Path:
    if not url.lower().startswith("https://"):
        raise ValueError("Image downloads require an HTTPS URL")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    resume_at = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "MobileBaseImager/0.2"}
    if resume_at:
        headers["Range"] = f"bytes={resume_at}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        resumed = resume_at > 0 and getattr(response, "status", None) == 206
        mode = "ab" if resumed else "wb"
        done = resume_at if resumed else 0
        total = int(response.headers.get("Content-Length") or 0) + done
        with partial.open(mode) as output:
            while chunk := response.read(CHUNK_SIZE):
                output.write(chunk)
                done += len(chunk)
                progress("DOWNLOADING IMAGE", done, total)
    actual = sha256_file(partial, progress, "VERIFYING DOWNLOAD")
    if expected_sha256 and actual != expected_sha256.upper():
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"Image checksum mismatch. Expected {expected_sha256}, received {actual}.")
    partial.replace(destination)
    write_checksum(destination, actual)
    return destination


def _copy_decompressed(source: BinaryIO, destination: Path, source_total: int, progress: Progress) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    with partial.open("wb") as output:
        while chunk := source.read(CHUNK_SIZE):
            output.write(chunk)
            position = getattr(source, "tell", lambda: 0)()
            progress("DECOMPRESSING IMAGE", min(position, source_total), source_total)
    partial.replace(destination)
    return destination


def decompress_image(source: Path, destination: Path, progress: Progress) -> Path:
    source_total = source.stat().st_size
    name = source.name.lower()
    if name.endswith(".img.zst"):
        with source.open("rb") as compressed:
            with zstandard.ZstdDecompressor().stream_reader(compressed) as reader:
                return _copy_decompressed(reader, destination, source_total, progress)
    if name.endswith(".img.gz"):
        with gzip.open(source, "rb") as reader:
            return _copy_decompressed(reader, destination, source_total, progress)
    if name.endswith(".img.xz"):
        with lzma.open(source, "rb") as reader:
            return _copy_decompressed(reader, destination, source_total, progress)
    if name.endswith(".zip"):
        with zipfile.ZipFile(source) as archive:
            members = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".img")]
            if len(members) != 1:
                raise ValueError("ZIP archives must contain exactly one .img file")
            with archive.open(members[0], "r") as reader:
                return _copy_decompressed(reader, destination, members[0].file_size, progress)
    raise ValueError("The selected image is not compressed in a supported format")


def decompressed_name(source: Path) -> str:
    name = source.name
    lowered = name.lower()
    for suffix in (".zst", ".gz", ".xz"):
        if lowered.endswith(suffix):
            return name[: -len(suffix)]
    if lowered.endswith(".zip"):
        with zipfile.ZipFile(source) as archive:
            members = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".img")]
            if len(members) != 1:
                raise ValueError("ZIP archives must contain exactly one .img file")
            return Path(members[0].filename).name
    return name


def prepare_image(source: Path, cache_dir: Path, progress: Progress) -> Path:
    if not is_supported_image(source):
        raise ValueError("Choose a .img, .img.zst, .img.gz, .img.xz, or single-image .zip file")
    if source.name.lower().endswith(".img"):
        return source
    destination = cache_dir / decompressed_name(source)
    if destination.exists() and destination.stat().st_mtime >= source.stat().st_mtime:
        progress("USING CACHED IMAGE", 1, 1)
        return destination
    return decompress_image(source, destination, progress)


def run_diskpart(lines: list[str]) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="ascii", newline="\r\n") as script:
        script.write("\n".join(lines) + "\n")
        script_path = Path(script.name)
    try:
        completed = subprocess.run(
            ["diskpart.exe", "/s", str(script_path)],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = completed.stdout.strip()
        failed = (
            completed.returncode
            or "diskpart has encountered an error" in output.lower()
            or "virtual disk service error" in output.lower()
            or "the selected disk is not valid" in output.lower()
        )
        if failed:
            raise RuntimeError(completed.stdout.strip() or completed.stderr.strip() or "DiskPart failed")
        return completed.stdout
    finally:
        script_path.unlink(missing_ok=True)


def run_linux_command(arguments: list[str], timeout: int = 300) -> str:
    completed = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"Command failed: {arguments[0]}")
    return completed.stdout


def linux_partitions(disk: Disk) -> list[str]:
    completed = subprocess.run(
        ["lsblk", "--list", "--noheadings", "--paths", "--output", "PATH,TYPE", disk.device_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode:
        return []
    return [line.split()[0] for line in completed.stdout.splitlines() if len(line.split()) >= 2 and line.split()[1] == "part"]


def unmount_linux_disk(disk: Disk) -> None:
    for partition in linux_partitions(disk):
        completed = subprocess.run(["umount", partition], capture_output=True, text=True, timeout=60)
        if completed.returncode and "not mounted" not in completed.stderr.lower():
            raise RuntimeError(completed.stderr.strip() or f"Could not unmount {partition}")


def format_disk(disk: Disk, filesystem: str = "exfat", label: str = "MOBILEBASE") -> None:
    if not is_safe_target(disk):
        raise RuntimeError("The selected disk does not pass the removable-media safety policy")
    filesystem = filesystem.lower()
    if filesystem not in {"exfat", "fat32", "ntfs"}:
        raise ValueError("Unsupported filesystem")
    if os.name == "nt" and filesystem == "fat32" and disk.size > 32 * 1000**3:
        raise ValueError("Windows cannot format FAT32 volumes larger than 32 GB; choose exFAT")
    safe_label = "".join(character for character in label.upper() if character.isalnum() or character in "-_ ")[:11].strip() or "MOBILEBASE"
    if os.name != "nt":
        unmount_linux_disk(disk)
        run_linux_command(["wipefs", "--all", disk.device_path])
        run_linux_command(["parted", "--script", disk.device_path, "mklabel", "msdos", "mkpart", "primary", "1MiB", "100%"])
        subprocess.run(["partprobe", disk.device_path], capture_output=True, timeout=30)
        partition = ""
        for _ in range(20):
            candidates = linux_partitions(disk)
            if candidates:
                partition = candidates[0]
                break
            time.sleep(0.25)
        if not partition:
            raise RuntimeError("Linux did not expose the new partition after formatting")
        command = {
            "exfat": ["mkfs.exfat", "-n", safe_label, partition],
            "fat32": ["mkfs.vfat", "-F", "32", "-n", safe_label, partition],
            "ntfs": ["mkfs.ntfs", "-F", "-L", safe_label, partition],
        }[filesystem]
        run_linux_command(command)
        return
    run_diskpart([
        f"select disk {disk.number}",
        "attributes disk clear readonly",
        "clean",
        "convert mbr",
        "create partition primary",
        f'format fs={filesystem} quick label="{safe_label}"',
        "assign",
        "exit",
    ])


def clean_disk(disk: Disk) -> None:
    if not is_safe_target(disk):
        raise RuntimeError("The selected disk does not pass the removable-media safety policy")
    if os.name != "nt":
        unmount_linux_disk(disk)
        run_linux_command(["wipefs", "--all", disk.device_path])
        return
    # Keep Windows from discovering and mounting partitions while their table is
    # still being written. Auto-mounting a half-written image can block the next
    # raw WriteFile call indefinitely on some USB card readers.
    run_diskpart([
        f"select disk {disk.number}",
        "attributes disk clear readonly",
        "clean",
        "offline disk",
        "exit",
    ])


def restore_disk_online(disk: Disk) -> None:
    if os.name == "nt":
        run_diskpart([f"select disk {disk.number}", "online disk", "exit"])


if os.name == "nt":
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
    FILE_FLAG_WRITE_THROUGH = 0x80000000
    FILE_BEGIN = 0
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _open_physical_drive(disk: Disk, write: bool = False):
    if os.name != "nt":
        return open(disk.device_path, "r+b" if write else "rb", buffering=0)
    access = GENERIC_READ | (GENERIC_WRITE if write else 0)
    share_mode = 0 if write else FILE_SHARE_READ | FILE_SHARE_WRITE
    flags = FILE_FLAG_SEQUENTIAL_SCAN | (FILE_FLAG_WRITE_THROUGH if write else 0)
    handle = kernel32.CreateFileW(
        disk.device_path,
        access,
        share_mode,
        None,
        OPEN_EXISTING,
        flags,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _read_handle(handle, amount: int) -> bytes:
    if os.name != "nt":
        return handle.read(amount)
    buffer = ctypes.create_string_buffer(amount)
    read = wintypes.DWORD()
    if not kernel32.ReadFile(handle, buffer, amount, ctypes.byref(read), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.raw[: read.value]


def _write_handle(handle, chunk: bytes) -> None:
    if os.name != "nt":
        written = handle.write(chunk)
        if written != len(chunk):
            raise RuntimeError("Linux reported an incomplete raw-disk write")
        return
    buffer = ctypes.create_string_buffer(chunk)
    written = wintypes.DWORD()
    if not kernel32.WriteFile(handle, buffer, len(chunk), ctypes.byref(written), None):
        raise ctypes.WinError(ctypes.get_last_error())
    if written.value != len(chunk):
        raise RuntimeError("Windows reported an incomplete raw-disk write")


def _flush_handle(handle) -> None:
    if os.name != "nt":
        handle.flush()
        os.fsync(handle.fileno())
        return
    if not kernel32.FlushFileBuffers(handle):
        raise ctypes.WinError(ctypes.get_last_error())


def _seek_handle_start(handle) -> None:
    if os.name != "nt":
        handle.seek(0)
        return
    if not kernel32.SetFilePointerEx(handle, 0, None, FILE_BEGIN):
        raise ctypes.WinError(ctypes.get_last_error())


def _close_handle(handle) -> None:
    if os.name != "nt":
        handle.close()
    else:
        kernel32.CloseHandle(handle)


def verify_image_against_disk(image: Path, disk: Disk, progress: Progress) -> str:
    if not is_safe_target(disk):
        raise RuntimeError("The selected disk does not pass the removable-media safety policy")
    image_size = image.stat().st_size
    if image_size > disk.size:
        raise RuntimeError(f"Image is {human_size(image_size)}, but target capacity is only {disk.size_label}")
    expected = sha256_file(image, progress, "HASHING SOURCE")
    handle = _open_physical_drive(disk, write=False)
    try:
        digest = hashlib.sha256()
        done = 0
        while done < image_size:
            chunk = _read_handle(handle, min(CHUNK_SIZE, image_size - done))
            if not chunk:
                raise RuntimeError("Target ended before verification completed")
            digest.update(chunk)
            done += len(chunk)
            progress("VERIFYING MEDIA", done, image_size)
        actual = digest.hexdigest().upper()
        if actual != expected:
            raise RuntimeError(f"Media does not match the image. Expected {expected}, received {actual}.")
        return actual
    finally:
        _close_handle(handle)


def flash_and_verify(image: Path, disk: Disk, progress: Progress, verify: bool = True) -> str:
    if not is_safe_target(disk):
        raise RuntimeError("The selected disk does not pass the removable-media safety policy")
    image_size = image.stat().st_size
    if image_size > disk.size:
        raise RuntimeError(f"Image is {human_size(image_size)}, but target capacity is only {disk.size_label}")
    if path_is_on_disk(image, disk):
        raise RuntimeError("The source image is stored on the selected target disk; move it before flashing")
    clean_disk(disk)
    handle = None
    operation_failed = False
    try:
        handle = _open_physical_drive(disk, write=True)
        image_digest = hashlib.sha256()
        done = 0
        with image.open("rb") as source:
            while chunk := source.read(CHUNK_SIZE):
                _write_handle(handle, chunk)
                image_digest.update(chunk)
                done += len(chunk)
                progress("FLASHING IMAGE", done, image_size)
        _flush_handle(handle)
        expected = image_digest.hexdigest().upper()
        if not verify:
            return expected
        _seek_handle_start(handle)
        target_digest = hashlib.sha256()
        done = 0
        while done < image_size:
            chunk = _read_handle(handle, min(CHUNK_SIZE, image_size - done))
            if not chunk:
                raise RuntimeError("Target ended before verification completed")
            target_digest.update(chunk)
            done += len(chunk)
            progress("VERIFYING FLASH", done, image_size)
        actual = target_digest.hexdigest().upper()
        if actual != expected:
            raise RuntimeError(f"Readback verification failed. Expected {expected}, received {actual}.")
        return expected
    except BaseException:
        operation_failed = True
        raise
    finally:
        if handle is not None:
            _close_handle(handle)
        try:
            restore_disk_online(disk)
        except Exception:
            if not operation_failed:
                raise


def backup_disk(disk: Disk, destination: Path, progress: Progress, compress: bool = True) -> BackupResult:
    if not is_safe_target(disk):
        raise RuntimeError("The selected disk does not pass the removable-media safety policy")
    if compress and not destination.name.lower().endswith(".img.zst"):
        destination = destination.with_suffix(destination.suffix + ".zst") if destination.suffix.lower() == ".img" else Path(str(destination) + ".img.zst")
    if not compress and not destination.name.lower().endswith(".img"):
        destination = Path(str(destination) + ".img")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path_is_on_disk(destination.parent, disk):
        raise RuntimeError("The backup destination is on the source disk; choose a different drive")
    free = shutil.disk_usage(destination.parent).free
    required = disk.size if not compress else min(disk.size, 2 * 1024**3)
    if free < required:
        raise RuntimeError(f"Backup destination has {human_size(free)} free; at least {human_size(required)} is required")
    partial = Path(str(destination) + ".partial")
    handle = _open_physical_drive(disk, write=False)
    raw_digest = hashlib.sha256()
    done = 0
    try:
        with partial.open("wb") as output:
            writer = zstandard.ZstdCompressor(level=5, threads=-1).stream_writer(output, closefd=False) if compress else output
            try:
                while done < disk.size:
                    chunk = _read_handle(handle, min(CHUNK_SIZE, disk.size - done))
                    if not chunk:
                        raise RuntimeError("Media ended before the backup completed")
                    writer.write(chunk)
                    raw_digest.update(chunk)
                    done += len(chunk)
                    progress("BACKING UP MEDIA", done, disk.size)
            finally:
                if writer is not output:
                    writer.close()
        partial.replace(destination)
        file_digest = sha256_file(destination, progress, "CHECKSUM BACKUP")
        write_checksum(destination, file_digest)
        return BackupResult(destination, file_digest, done, compress)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        _close_handle(handle)


def disk_debug_json(disks: Iterable[Disk]) -> str:
    return json.dumps([asdict(disk) for disk in disks], indent=2)

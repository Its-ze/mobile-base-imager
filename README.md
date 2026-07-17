# Mobile Base Imager

Mobile Base Imager is a native Windows and Linux disk-imaging workspace for Raspberry Pi and removable-media projects. It downloads the verified Mobile Base appliance, opens common image formats, flashes and verifies media, compares existing cards with images, creates full-device backups, formats cards, and maintains checksums and caches.

## Imaging workflows

- **Flash** raw `.img`, `.img.zst`, `.img.gz`, `.img.xz`, and single-image `.zip` files.
- **Verify** an already-written card against an image without changing the card.
- **Backup** every byte of an SD/USB device to `.img` or compressed `.img.zst`.
- **Format** removable media as exFAT, FAT32, or NTFS with a custom volume label.
- **Download** the official Mobile Base Stable image with enforced SHA-256 verification.
- **Download URL** for other HTTPS images, with optional publisher checksum and resumable partial download.
- **Image tools** calculate SHA-256 sidecars, open app storage, clear cache, and save operation logs.

## Safety model

- Boot and system disks are always excluded.
- Only removable USB/SD devices up to 2 TB are listed.
- Raw media access requires Administrator privileges on Windows or root through `pkexec` on Linux.
- Every erase shows the device path or disk number, model, capacity, and bus type.
- The operator must type the exact `ERASE ...` confirmation before formatting or flashing.
- Official downloads enforce their published SHA-256.
- Full byte-for-byte post-write verification is enabled by default.
- Backups and verify-only operations open devices read-only.
- The app refuses to flash from, or save a backup onto, the device being imaged.

Unplug unrelated external storage and confirm the displayed model, capacity, and device identifier before approving an erase.

## Downloads

**https://its-ze.github.io/mobile-base-imager/**

GitHub releases include:

- standalone Windows x64 EXE and portable ZIP;
- standalone Linux x86_64 binary and portable `.tar.gz`;
- Debian/Ubuntu amd64 `.deb` package;
- a standalone checksum-verifying Linux `.sh` installer;
- the Mobile Base Raspberry Pi image and published checksums.

## Linux installation

Ubuntu 24.04+, Debian 13+, and compatible x86_64 distributions with glibc 2.39+ are supported.

Download and run the standalone installer:

```bash
curl -fL https://github.com/Its-ze/mobile-base-imager/releases/latest/download/install-mobile-base-imager.sh -o install-mobile-base-imager.sh
bash install-mobile-base-imager.sh
```

The installer downloads the matching Debian package, verifies its published SHA-256, installs required system packages through APT, creates the desktop entry, and runs the built-in self-test.

```bash
sudo apt install ./mobile-base-imager_0.3.1_linux_amd64.deb
```

The portable Linux archive can run without installation. Extract it and launch `./mobile-base-imager`, or run `sudo ./install.sh` to add the desktop entry.

Linux discovery uses `lsblk`; destructive operations use `wipefs`, `parted`, and the appropriate `mkfs` utility. The app's **Restart as root** button elevates only after the operator chooses a raw-media workflow.

## Flash Mobile Base

1. Open Mobile Base Imager and elevate when requested.
2. Insert the SD card and select **Refresh**.
3. Choose **Mobile Base Stable**, or browse to a supported image.
4. Confirm the target identifier, model, capacity, and bus.
5. Choose **Flash Image + Verify** and complete the exact typed confirmation.
6. Keep the card connected until writing and readback verification complete.

## Development

Windows:

```powershell
.\scripts\bootstrap.ps1
& "$env:LOCALAPPDATA\MobileBaseImagerTooling\venv\Scripts\python.exe" -m pytest -q
.\scripts\build-release.ps1
```

Linux x86_64 through WSL Ubuntu:

```powershell
.\scripts\build-linux.ps1
```

The Windows build is not Authenticode-signed and the Linux DEB does not yet have a repository signature. Always verify `checksums.txt` from the matching GitHub release.

## Publishing

`scripts\publish.ps1` builds both operating systems, pushes the repository, configures Pages, and uploads the complete release asset set.

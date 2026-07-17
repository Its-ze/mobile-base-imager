# Mobile Base Imager

Mobile Base Imager is a complete Windows disk-imaging workspace for Raspberry Pi and removable-media projects. It can download the verified Mobile Base appliance, open common image formats, flash and verify media, compare an existing card with an image, make full-device backups, format cards, and maintain checksums and image caches.

## Imaging workflows

- **Flash** raw `.img`, `.img.zst`, `.img.gz`, `.img.xz`, and single-image `.zip` files.
- **Verify** an already-written card against an image without changing the card.
- **Backup** every byte of an SD/USB device to `.img` or compressed `.img.zst`.
- **Format** removable media as exFAT, FAT32, or NTFS with a custom volume label.
- **Download** the official Mobile Base Stable image with enforced SHA-256 verification.
- **Download URL** for other HTTPS images, with an optional publisher checksum and resumable partial download.
- **Image tools** calculate SHA-256 sidecars, open app storage, clear prepared-image cache, and save operation logs.

## Safety model

- Windows boot and system disks are always excluded.
- Only removable USB/SD devices up to 2 TB are listed.
- Raw media access requires Administrator privileges.
- Every erase shows disk number, model, capacity, and bus type.
- The operator must type `ERASE DISK N` before formatting or flashing begins.
- Official downloads enforce their published SHA-256 before use.
- Compressed local images use adjacent checksum sidecars when available and create a local integrity sidecar when explicitly approved.
- Full byte-for-byte post-write verification is enabled by default.
- Backups and verify-only operations open the device read-only.

No software can identify every unusual card reader or USB bridge perfectly. Unplug unrelated external storage and confirm the displayed model, capacity, and disk number before approving an erase.

## Download

The public download page is intended to be:

`https://its-ze.github.io/mobile-base-imager/`

GitHub releases include the standalone Windows EXE, a portable ZIP, the Mobile Base Pi image, its checksum, and `checksums.txt`.

## Flash Mobile Base

1. Open `MobileBaseImager.exe` and choose **Restart as Admin**.
2. Insert the SD card and select **Refresh**.
3. Choose **Mobile Base Stable**, or browse to a supported local image.
4. Select the card by disk number, model, capacity, and bus.
5. Choose **Flash Image + Verify** and complete the exact typed confirmation.
6. Keep the card connected until both writing and readback verification complete.

On first boot, Mobile Base creates its identity and pairing information, starts its setup Wi-Fi, and exposes network onboarding through the Android app or browser.

## Development

```powershell
cd 'F:\Dropbox\Dev Ops\Mobile Base Imager'
.\scripts\bootstrap.ps1
& "$env:LOCALAPPDATA\MobileBaseImagerTooling\venv\Scripts\python.exe" -m pytest -q
& "$env:LOCALAPPDATA\MobileBaseImagerTooling\venv\Scripts\python.exe" -m app.mobile_base_imager --demo
.\scripts\build-release.ps1
```

The release is self-contained for Windows 10/11 x64; Python is not required on the destination computer.

Version 0.2.0 is not Authenticode-signed, so Microsoft Defender SmartScreen may show an unknown-publisher or reputation prompt. Verify the published SHA-256 checksum before running it. A future release can remove this warning after a Windows code-signing certificate is added.

## Publishing

Authenticate GitHub CLI first:

```powershell
gh auth login
gh auth status
.\scripts\publish.ps1
```

Publishing creates or updates `Its-ze/mobile-base-imager`, pushes `main`, configures the Pages workflow, and uploads the versioned release artifacts.

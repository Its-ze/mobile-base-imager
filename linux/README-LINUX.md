# Mobile Base Imager for Linux

The Linux build supports the same flash, verify, full-backup, format, download, checksum, and cache workflows as the Windows build.

## Supported systems

- Ubuntu 24.04 or newer
- Debian 13 or newer
- x86_64 desktop Linux distributions with glibc 2.39 or newer

## Install the DEB

```bash
sudo apt install ./mobile-base-imager_VERSION_linux_amd64.deb
```

## Run the portable archive

Extract the archive and run `./mobile-base-imager`, or install it with `sudo ./install.sh`.

Disk discovery is unprivileged. Flashing, formatting, raw verification, and full-media backup require root access; use the app's **Restart as root** control when prompted.

Linux targets are discovered through `lsblk`. Only removable USB or SD-class devices are offered. A device holding `/`, `/boot`, or `/boot/efi` is always excluded.

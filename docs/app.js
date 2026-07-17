fetch('release-manifest.json', {cache: 'no-store'})
  .then(response => {
    if (!response.ok) throw new Error('Release manifest unavailable');
    return response.json();
  })
  .then(manifest => {
    document.querySelector('#download-exe').href = manifest.exeUrl;
    document.querySelector('#download-bottom').href = manifest.exeUrl;
    document.querySelector('#download-linux').href = manifest.linuxAppImageUrl;
    document.querySelector('#download-linux-deb').href = manifest.linuxDebUrl;
    document.querySelector('#download-linux-installer').href = manifest.linuxInstallerUrl;
    document.querySelector('#download-linux-appimage').href = manifest.linuxAppImageUrl;
    document.querySelector('#download-image').href = manifest.imageUrl;
    document.querySelector('#release-version').textContent = `v${manifest.appVersion}`;
    document.querySelector('#download-meta').textContent = `Version ${manifest.appVersion} · Windows + Linux x64 · Mobile Base ${manifest.imageVersion}`;
  })
  .catch(() => {
    document.querySelector('#download-meta').textContent = 'Open the latest GitHub release for downloads and checksums.';
  });

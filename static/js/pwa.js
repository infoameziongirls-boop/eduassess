(function () {
  'use strict';

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', {updateViaCache: 'none'})
      .catch(error => console.error('Unable to register the EduAssess service worker:', error));
  }

  const installButton = document.getElementById('pwaInstallButton');
  if (!installButton) return;

  let installPrompt = null;
  const isInstalled = () =>
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true;

  if (isInstalled()) return;

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
    installButton.hidden = false;
  });

  installButton.addEventListener('click', async () => {
    if (!installPrompt) return;
    installButton.disabled = true;
    try {
      const prompt = installPrompt;
      installPrompt = null;
      await prompt.prompt();
      const result = await prompt.userChoice;
      if (result.outcome === 'accepted') installButton.hidden = true;
    } catch (error) {
      console.error('Unable to start PWA installation:', error);
    } finally {
      installButton.disabled = false;
    }
  });

  window.addEventListener('appinstalled', () => {
    installPrompt = null;
    installButton.hidden = true;
  });
})();

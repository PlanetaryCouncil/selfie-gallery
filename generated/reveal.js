// The gallery's secure ultra reveal runs entirely on GitHub Pages.
// Originals are public; the operator explicitly allows a direct bypass.
function attachPortraitReveal(card, onReveal = () => {}) {
  const button = card.querySelector('.generated-reveal');
  const status = card.querySelector('.generated-status');
  button.addEventListener('click', async () => {
    button.disabled = true;
    status.textContent = 'Computing proof of work…';
    const started = performance.now();
    let worker, timer;
    try {
      const bytes = crypto.getRandomValues(new Uint8Array(32));
      const challenge = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
      const nonce = await new Promise((resolve, reject) => {
        worker = new Worker('generated/reveal-worker.js');
        timer = setTimeout(() => reject(new Error('Work timed out. Try again.')), 90000);
        worker.onmessage = ({data}) => data.error
          ? reject(new Error(data.error)) : resolve(data.nonce);
        worker.onerror = () => reject(new Error('Could not run the work. Try again.'));
        worker.postMessage({challenge, bits: 13});
      });
      // Check the worker's answer before revealing the hosted original.
      const hash = new Uint8Array(await crypto.subtle.digest('SHA-256',
        new TextEncoder().encode(challenge + ':' + nonce)));
      if (hash[0] !== 0 || (hash[1] >>> 3) !== 0) throw new Error('Invalid proof. Try again.');
      await new Promise(resolve => setTimeout(resolve, Math.max(0, 1000 - (performance.now() - started))));
      const image = new Image();
      image.alt = card.dataset.generatedAlt || 'Fully fledged selfie';
      image.onload = () => {
        status.textContent = 'Proof complete.';
        button.hidden = true;
      };
      image.onerror = () => {
        image.remove();
        status.textContent = 'Image could not load. Try again.';
        button.disabled = false;
      };
      status.textContent = 'Proof complete. Loading portrait…';
      image.src = card.dataset.generatedSrc;
      card.appendChild(image);
      onReveal(image);
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
    } finally {
      clearTimeout(timer);
      if (worker) worker.terminate();
    }
  });
}

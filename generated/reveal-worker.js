self.onmessage = async ({data: {challenge, bits}}) => {
  try {
    const encoder = new TextEncoder();
    const bytes = Math.floor(bits / 8), rest = bits % 8;
    for (let nonce = 0; nonce < Number.MAX_SAFE_INTEGER; nonce++) {
      const hash = new Uint8Array(await crypto.subtle.digest('SHA-256',
        encoder.encode(challenge + ':' + nonce)));
      if (hash.slice(0, bytes).every(b => b === 0) &&
          (!rest || (hash[bytes] >>> (8 - rest)) === 0)) {
        postMessage({nonce: String(nonce)});
        return;
      }
    }
    throw new Error('No solution found. Try again.');
  } catch (error) {
    postMessage({error: error.message});
  }
};

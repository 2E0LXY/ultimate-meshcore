// Self-tests for keygen-core.js. Used by keygen-test.html; also runs under Node 18+:
//   node flasher/keygen-tests.js
import { pubFromPrv, fromHex, toHex, checkPrefix, validatePrv, scalarMulBase, encodePoint, clampScalar, cache, addCached } from './keygen-core.js';

// Vector from src/Identity.cpp (LocalIdentity::validatePrivateKey, "known good test client keypair").
const PRV = '7065e18fd9fabb70c1ed90dca19907de698c88b709ea146eafd93d9b830c7b60'
          + 'c4681193c79bbc39945ba8064104bb618f8fd7a84a0af6f57033d6e8ddcd6471';
const PUB = '1ec77175b0918ed206f9ae04ec136d6d5d4315bb26305427f645b492e9350c10';

export async function runTests() {
  const r = [];
  const t = (name, fn) => { try { const v = fn(); r.push({ name, ok: v === true, info: String(v) }); } catch (e) { r.push({ name, ok: false, info: e.message }); } };

  t('firmware vector (src/Identity.cpp): derived public key matches', () => { const g = toHex(pubFromPrv(fromHex(PRV))); return g === PUB || g; });
  t('firmware vector: prv.key is 128 hex chars and passes validatePrv', () => PRV.length === 128 && (validatePrv(PRV) === '' || validatePrv(PRV)));

  if (globalThis.crypto && crypto.subtle) {
    // RFC 8032 section 7.1, test 1: SHA-512(seed), clamp, derive.
    const seed = fromHex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60');
    const prv = new Uint8Array(64); prv.set(new Uint8Array(await crypto.subtle.digest('SHA-512', seed)));
    prv[0] &= 248; prv[31] &= 63; prv[31] |= 64;
    const got = toHex(pubFromPrv(prv)), want = 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a';
    t('RFC 8032 test 1: derived public key matches', () => got === want || got);
  }

  t('incremental walk (s += 8, P += 8G, as the worker does) equals full multiplication', () => {
    const s0 = clampScalar(Uint8Array.from({ length: 32 }, (_, i) => (i * 37 + 11) & 255));
    const step = cache(scalarMulBase(8n));
    let p = scalarMulBase(s0);
    for (let k = 1; k <= 25; k++) p = addCached(p, step);
    return toHex(encodePoint(p)) === toHex(encodePoint(scalarMulBase(s0 + 8n * 25n))) || 'mismatch';
  });

  t('checkPrefix rejects 00, ff, FF1, 9 chars, non-hex, empty', () => ['00', 'ff', 'FF1', '123456789', 'xyz', ''].every((p) => checkPrefix(p) !== ''));
  t('checkPrefix accepts 0, f, 1e, 2e0, abcdef12', () => ['0', 'f', '1e', '2e0', 'abcdef12'].every((p) => checkPrefix(p) === ''));
  t('validatePrv rejects wrong length and non-hex', () => validatePrv('00') !== '' && validatePrv('zz'.repeat(64)) !== '');
  return r;
}

// Node entry point
if (typeof process !== 'undefined' && process.argv && import.meta.url === `file://${process.argv[1]}`) {
  const out = await runTests();
  for (const x of out) console.log((x.ok ? 'PASS ' : 'FAIL ') + x.name + (x.ok ? '' : ' - ' + x.info));
  process.exit(out.every((x) => x.ok) ? 0 : 1);
}

/**
 * Trade Republic — extracteur des listes /browse/* vers CSV.
 *
 * Ce snippet se colle dans la console DevTools (Chrome/Firefox/Brave/Arc) en
 * étant sur une des pages :
 *   https://app.traderepublic.com/browse/stock
 *   https://app.traderepublic.com/browse/crypto
 *   https://app.traderepublic.com/browse/fund
 *   https://app.traderepublic.com/browse/bond
 *   https://app.traderepublic.com/browse/derivative
 *   https://app.traderepublic.com/browse/mutualFund
 *
 * Mode d'emploi
 * -------------
 * 1. Ouvre la page dans une fenêtre incognito (pas de login requis).
 * 2. F12 → onglet « Console ».
 * 3. Copie/colle tout ce fichier puis Entrée.
 * 4. Tape :   await scrapeTR()
 * 5. Le script scrolle automatiquement jusqu'au bas de la liste (peut être
 *    long sur 3000+ items — il loggue son avancement).
 * 6. À la fin, un CSV est :
 *      - copié dans le clipboard (paste-le dans un fichier .csv),
 *      - également loggué dans la console au cas où le clipboard est bloqué.
 *
 * Sortie
 * ------
 * Une ligne « code,raw_label » par instrument unique. Le `code` est ce que TR
 * met dans son URL (souvent ISIN pour les stocks/funds, ticker symbolique
 * pour la crypto). Le `raw_label` est le texte visible de l'ancre — souvent
 * "Nom de la société\nTICKER" ou similaire. On nettoie en Python côté repo.
 *
 * Option : passer { maxIdleSteps: 40 } à scrapeTR() si tu sens qu'on s'arrête
 * trop tôt sur des listes très lentes à charger.
 */
async function scrapeTR(opts = {}) {
  const { maxIdleSteps = 25, scrollDelayMs = 400 } = opts;

  // 1. Trouve le conteneur scrollable. Le DOM TR varie : on essaie plusieurs
  //    candidats et on prend le premier qui a un scrollHeight > clientHeight.
  const findScroller = () => {
    const candidates = [
      document.querySelector('main'),
      ...document.querySelectorAll('[class*="scroll"]'),
      ...document.querySelectorAll('[class*="Browse"]'),
      document.scrollingElement,
      document.body,
    ].filter(Boolean);
    for (const c of candidates) {
      if (c.scrollHeight > c.clientHeight + 50) return c;
    }
    return document.scrollingElement || document.body;
  };
  const scroller = findScroller();
  console.log('[TR] scroller =', scroller.tagName, scroller.className || '');

  // 2. Auto-scroll jusqu'à ce que la hauteur arrête de croître.
  let lastHeight = 0, idle = 0, iter = 0;
  console.log('[TR] auto-scroll démarré…');
  while (idle < maxIdleSteps && iter < 5000) {
    scroller.scrollTo(0, scroller.scrollHeight);
    await new Promise(r => setTimeout(r, scrollDelayMs));
    if (scroller.scrollHeight === lastHeight) {
      idle++;
    } else {
      idle = 0;
      lastHeight = scroller.scrollHeight;
    }
    iter++;
    if (iter % 25 === 0) {
      console.log(`[TR] iter ${iter} · h=${scroller.scrollHeight} · idle=${idle}/${maxIdleSteps}`);
    }
  }
  console.log(`[TR] scroll terminé après ${iter} itérations, hauteur finale ${scroller.scrollHeight}`);

  // 3. Walk les ancres avec un href TR vers un instrument.
  //    URL patterns observés : /stock/<ISIN>, /crypto/<symbol>, /fund/<ISIN>,
  //    /bond/<ISIN>, /derivative/<wkn>, /mutualFund/<ISIN>, /instrument/<ISIN>.
  const PATH_RE = /\/(?:stock|crypto|fund|bond|derivative|mutualFund|instrument|etf)\/([A-Z0-9.\-]+)/i;
  const rows = new Map(); // code → { code, label, href }
  const anchors = document.querySelectorAll('a[href]');
  console.log(`[TR] ${anchors.length} ancres totales sur la page`);
  let kept = 0;
  for (const a of anchors) {
    const href = a.getAttribute('href') || a.href || '';
    const m = href.match(PATH_RE);
    if (!m) continue;
    const code = m[1].toUpperCase();
    // Filtre des codes trop courts pour être réels (parfois des routes /stock = collection page)
    if (code.length < 3) continue;
    const text = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!text) continue;
    if (!rows.has(code)) {
      rows.set(code, { code, label: text, href });
      kept++;
    }
  }
  console.log(`[TR] ${kept} instruments uniques retenus`);

  // 4. CSV.
  const escape = s => {
    if (s == null) return '';
    const str = String(s);
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };
  const lines = ['code,raw_label,href'];
  for (const r of rows.values()) {
    lines.push(`${escape(r.code)},${escape(r.label)},${escape(r.href)}`);
  }
  const csv = lines.join('\n');

  // 5. Clipboard (+ fallback console).
  try {
    await navigator.clipboard.writeText(csv);
    console.log(`[TR] ✅ CSV copié dans le clipboard (${kept} lignes). Paste-le dans un .csv.`);
  } catch (e) {
    console.warn('[TR] clipboard refusé, voici le CSV brut :');
    console.log(csv);
  }

  // 6. Petit aperçu pour vérif visuelle.
  console.table(Array.from(rows.values()).slice(0, 5));
  return { count: kept, sample: Array.from(rows.values()).slice(0, 10) };
}

console.log('[TR] scraper chargé · appel :  await scrapeTR()');

// Rack favorability and performance are descriptive heuristics, not win odds.
(function(root) {
  const VERSION = 1;
  // Counts from the bundled Quackle crossplay.quackle_alphabet (100 tiles).
  const TILE_COUNTS = Object.freeze({
    A: 9, B: 2, C: 2, D: 4, E: 12, F: 2, G: 3, H: 3, I: 8,
    J: 1, K: 1, L: 4, M: 2, N: 5, O: 8, P: 2, Q: 1, R: 6,
    S: 5, T: 6, U: 3, V: 2, W: 2, X: 1, Y: 2, Z: 1, '?': 3
  });
  const SAMPLE_COUNT = 2048;
  const referenceCache = new Map();

  function rackStrength(rack) {
    const counts = {};
    for (const tile of rack) counts[tile] = (counts[tile] || 0) + 1;
    const blanks = counts['?'] || 0;
    const vowels = [...rack].filter(tile => 'AEIOU'.includes(tile)).length;
    // Blanks can supply either side of the vowel/consonant balance.
    const target = rack.length * 0.42;
    const imbalance = Math.max(0, vowels - target, target - vowels - blanks);
    const repeats = Object.entries(counts).filter(([tile]) => tile !== '?')
      .reduce((sum, [, count]) => sum + count * (count - 1) / 2, 0);
    const flexible = [...rack].filter(tile => 'ERNT'.includes(tile)).length;
    const awkward = (counts.J || 0) * 2 + (counts.V || 0) * 1.5 +
      (counts.W || 0) + (counts.K || 0);
    return blanks * 12 + (counts.S || 0) * 3 + flexible * 0.8 -
      imbalance * 2.5 - repeats * 1.5 - awkward -
      ((counts.Q && !counts.U && !blanks) ? 6 : 0);
  }

  function rackFavorability(turn) {
    const rack = turn && turn.rack;
    const grid = turn && turn.grid;
    if (typeof rack !== 'string' || !/^[A-Z?]{1,7}$/.test(rack) ||
        !Array.isArray(grid) || grid.length !== 15 ||
        !grid.every(row => typeof row === 'string' && /^[A-Za-z.]{15}$/.test(row))) return null;
    const remaining = { ...TILE_COUNTS };
    for (const tile of grid.join('')) {
      if (tile === '.') continue;
      const physical = tile === tile.toLowerCase() ? '?' : tile;
      if (--remaining[physical] < 0) return null;
    }
    const available = { ...remaining };
    for (const tile of rack) if (--available[tile] < 0) return null;
    // Include the actual rack in the pool: compare with all tiles off the board,
    // without using later racks or pretending we know the opponent's tiles.
    const key = rack.length + ':' + Object.values(remaining).join(',');
    let reference = referenceCache.get(key);
    if (!reference) {
      const pool = Object.entries(remaining).flatMap(([tile, count]) => Array(count).fill(tile));
      let seed = 2166136261;
      for (const char of key) seed = Math.imul(seed ^ char.charCodeAt(0), 16777619) >>> 0;
      reference = [];
      for (let sample = 0; sample < SAMPLE_COUNT; sample++) {
        const tiles = pool.slice();
        let drawn = '';
        for (let index = 0; index < rack.length; index++) {
          seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
          const chosen = index + Math.floor(seed / 4294967296 * (tiles.length - index));
          [tiles[index], tiles[chosen]] = [tiles[chosen], tiles[index]];
          drawn += tiles[index];
        }
        reference.push(rackStrength(drawn));
      }
      if (referenceCache.size >= 256) referenceCache.clear();
      referenceCache.set(key, reference);
    }
    const strength = rackStrength(rack);
    const percentile = 100 * reference.reduce((sum, score) =>
      sum + (score < strength - 1e-9 ? 1 : Math.abs(score - strength) < 1e-9 ? 0.5 : 0), 0) / reference.length;
    return {
      percentile,
      band: percentile < 35 ? 'Tough' : percentile > 65 ? 'Favorable' : 'Typical',
      blanks: [...rack].filter(tile => tile === '?').length,
      samples: SAMPLE_COUNT
    };
  }

  function opportunityContext(turn, moves, frequencies, wordForMove) {
    const candidates = moves.filter(move => Number.isFinite(move.equity)).map(move => {
      const word = wordForMove(turn, move);
      const zipf = word ? frequencies.get(word.toLowerCase()) : undefined;
      // Missing words are unknown, not rare. Keep their full equity benchmark.
      const allowance = Number.isFinite(zipf) ? Math.min(6, Math.max(0, 4 - zipf) * 2) : 0;
      return { equity: move.equity, accessibleEquity: move.equity - allowance, word, zipf };
    });
    if (!candidates.length) return null;
    const best = candidates.reduce((top, candidate) => candidate.equity > top.equity ? candidate : top);
    return {
      version: VERSION,
      accessibleEquity: Math.max(...candidates.map(candidate => candidate.accessibleEquity)),
      bestWord: best.word,
      bestWordZipf: Number.isFinite(best.zipf) ? best.zipf : null,
      knownCandidates: candidates.filter(candidate => Number.isFinite(candidate.zipf)).length,
      candidateCount: candidates.length
    };
  }

  function performance(point, rack) {
    if (!point || point.category === 'unrated' || !Number.isFinite(point.loss) || point.loss < 0) return null;
    const execution = 100 / (1 + point.loss / 10);
    const context = point.opportunity;
    if (!rack || context?.version !== VERSION || !Number.isFinite(context.accessibleEquity) ||
        !Number.isFinite(point.playedEquity)) return { execution };
    const adjustedLoss = Math.min(point.loss, Math.max(0, context.accessibleEquity - point.playedEquity));
    return {
      execution,
      adjustedLoss,
      adjusted: 100 / (1 + adjustedLoss / 10),
      weight: 1 + (100 - rack.percentile) / 100
    };
  }

  function summarize(review, points = []) {
    const byTurn = new Map(points.map(point => [point.turnIndex, point]));
    const turns = (review.turns || []).flatMap((turn, index) => {
      if (!turn.mine) return [];
      const rack = rackFavorability(turn);
      const point = byTurn.get(index);
      return [{ index, turn, rack, point, performance: performance(point, rack) }];
    });
    const racks = turns.filter(item => item.rack);
    const rated = turns.filter(item => item.performance);
    const adjusted = rated.filter(item => Number.isFinite(item.performance.adjusted));
    const totalWeight = adjusted.reduce((sum, item) => sum + item.performance.weight, 0);
    return {
      turns,
      rackCount: racks.length,
      favorability: racks.length ? racks.reduce((sum, item) => sum + item.rack.percentile, 0) / racks.length : null,
      ratedCount: rated.length,
      execution: rated.length ? rated.reduce((sum, item) => sum + item.performance.execution, 0) / rated.length : null,
      adjustedCount: adjusted.length,
      adjusted: totalWeight ? adjusted.reduce((sum, item) => sum + item.performance.adjusted * item.performance.weight, 0) / totalWeight : null,
      knownWords: adjusted.reduce((sum, item) => sum + item.point.opportunity.knownCandidates, 0),
      candidateWords: adjusted.reduce((sum, item) => sum + item.point.opportunity.candidateCount, 0)
    };
  }

  const api = { VERSION, TILE_COUNTS, rackFavorability, opportunityContext, performance, summarize };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.CrossplayLuck = api;
})(globalThis);

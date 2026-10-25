importScripts('quackle.js');

let modulePromise = null;

async function getModule() {
  if (!modulePromise) {
    modulePromise = (async () => {
      const module = await QuackleModule();
      if (!module.initEngine('/data')) throw new Error('Quackle engine initialization failed');
      return module;
    })();
  }
  return modulePromise;
}

function customMoveKey(payload) {
  let grid;
  try { grid = JSON.parse(payload.gridJson); }
  catch (_) { throw new Error('A valid 15×15 board is required.'); }
  if (!Array.isArray(grid) || grid.length !== 15 ||
      !grid.every(row => typeof row === 'string' && /^[A-Za-z.]{15}$/.test(row))) {
    throw new Error('A valid 15×15 board is required.');
  }
  const rack = String(payload.rack || '');
  if (!/^[A-Z?]{1,7}$/.test(rack)) throw new Error('A rack with 1 to 7 letters or blanks is required.');
  const { bagCount, finalTurnsRemaining } = payload;
  if (!Number.isInteger(bagCount) || bagCount < 0 ||
      !Number.isInteger(finalTurnsRemaining) ||
      (bagCount === 0 ? ![1, 2].includes(finalTurnsRemaining) : finalTurnsRemaining !== 0)) {
    throw new Error('Enter a valid bag count and Crossplay final-turn state first.');
  }
  const unseen = 100 - grid.join('').replace(/\./g, '').length - rack.length;
  if (unseen - bagCount < 0 || unseen - bagCount > 7) {
    throw new Error('The board, rack, and bag count must leave 0 to 7 tiles for the opponent.');
  }
  const move = payload.customMove || {};
  const word = String(move.word || '').trim();
  const square = String(move.square || '').trim().toUpperCase().match(/^([A-O])(1[0-5]|[1-9])$/);
  if (!/^[A-Za-z.]{1,15}$/.test(word)) throw new Error('Enter a word using letters, or . for existing tiles.');
  if (!square) throw new Error('Enter a start square from A1 to O15, such as G8.');
  if (!['across', 'down'].includes(move.direction)) throw new Error('Choose Across or Down.');
  let row = Number(square[2]) - 1;
  let col = 'ABCDEFGHIJKLMNO'.indexOf(square[1]);
  const remaining = rack.split('');
  const placed = [];
  for (const letter of word) {
    if (row >= 15 || col >= 15) throw new Error('The move runs off the board.');
    const existing = grid[row][col];
    if (existing !== '.') {
      if (letter !== '.' && letter.toUpperCase() !== existing.toUpperCase()) {
        throw new Error('The word conflicts with an existing tile. Include that letter or use . for it.');
      }
    } else {
      if (letter === '.') throw new Error('Use . only on a square that already has a tile.');
      const tile = letter === letter.toLowerCase() ? '?' : letter;
      const index = remaining.indexOf(tile);
      if (index < 0) throw new Error('The rack does not contain the required tiles. Use lowercase for a blank.');
      remaining.splice(index, 1);
      placed.push(`${row},${col}:${letter}`);
    }
    if (move.direction === 'across') col++;
    else row++;
  }
  if (!placed.length) throw new Error('The move must place at least one new tile.');
  return { grid, key: placed.sort().join('|') };
}

// Match the physical placements, including assigned blanks. This also recognizes
// one-tile plays when Quackle writes them in the perpendicular direction.
function candidateKey(move, grid) {
  if (move.action !== 'place') return '';
  const across = String(move.position).match(/^(\d{1,2})([A-O])$/);
  const down = String(move.position).match(/^([A-O])(\d{1,2})$/);
  if (!across && !down) return '';
  let row = Number(across ? across[1] : down[2]) - 1;
  let col = 'ABCDEFGHIJKLMNO'.indexOf(across ? across[2] : down[1]);
  const placed = [];
  for (const letter of move.tiles) {
    if (!grid[row] || col >= 15) return '';
    if (grid[row][col] === '.' && letter !== '.') placed.push(`${row},${col}:${letter}`);
    if (across) col++;
    else row++;
  }
  return placed.sort().join('|');
}

function simulate(module, payload, numMoves = payload.numMoves, iterations = payload.iterations) {
  return module.simulateKibitz(
    payload.gridJson, payload.rack, payload.playerScore, payload.opponentScore,
    numMoves, iterations, payload.bagCount, payload.finalTurnsRemaining,
  );
}

function evaluateCustomMove(module, payload, simulateWin) {
  const { grid, key } = customMoveKey(payload);
  // Ask for the complete legal list rather than the usual short list. The
  // bundled engine has no binding for injecting a single simulation candidate.
  const limit = 1000000;
  const generated = module.kibitz(payload.gridJson, payload.rack,
    payload.playerScore, payload.opponentScore, limit);
  if (generated.error) throw new Error(generated.error);
  if (!Array.isArray(generated.moves) || generated.moves.length >= limit) {
    throw new Error('Quackle could not return the complete move list for this position.');
  }
  if (payload.bagCount < 7) generated.moves = generated.moves.filter(move => move.action !== 'exchange');
  const index = generated.moves.findIndex(move => candidateKey(move, grid) === key);
  if (index < 0) {
    throw new Error('This move is not legal in Quackle’s dictionary at this position. Check the word, connecting words, start square, and direction.');
  }
  const selected = generated.moves[index];
  const best = generated.moves.reduce((top, move) => move.equity > top.equity ? move : top, selected);
  const evaluation = { selected, best, staticRank: index + 1, legalMoveCount: generated.moves.length, simulated: false };
  if (!simulateWin) return evaluation;
  if (!Number.isInteger(payload.iterations) || payload.iterations < 1 || payload.iterations > 277) {
    throw new Error('Simulation iterations must be between 1 and 277.');
  }
  let count = Math.max(15, index + 1);
  // Endgame ranking can differ from the static list. Check candidate inclusion
  // with one sample before committing to all requested simulation rounds.
  let result;
  while (true) {
    result = simulate(module, payload, count, 1);
    if (result.error) throw new Error(result.error);
    if (!result.simulated || !Array.isArray(result.moves)) throw new Error('Quackle could not simulate this position.');
    if (result.moves.some(move => candidateKey(move, grid) === key)) break;
    if (count >= generated.moves.length) throw new Error('Quackle could not include this move in its simulation.');
    count = Math.min(generated.moves.length, count * 2);
  }
  result = payload.iterations === 1 ? result : simulate(module, payload, count);
  if (result.error) throw new Error(result.error);
  const playToEnd = payload.bagCount <= 21;
  if (!result.simulated || result.iterationsCompleted !== payload.iterations ||
      result.iterationsRequested !== payload.iterations ||
      result.bagCount !== payload.bagCount || result.finalTurnsRemaining !== payload.finalTurnsRemaining ||
      result.playToEnd !== playToEnd || result.simulationMode !== (playToEnd ? 'play-to-end' : '2-ply') ||
      result.plies !== (playToEnd ? -1 : 2) || result.winModel !== (playToEnd ? 'terminal' : 'bogowin') ||
      result.candidateCount !== result.moves.length ||
      result.totalPlayaheads !== payload.iterations * result.moves.length ||
      !result.moves.length || !result.moves.every(move =>
        move.samples === payload.iterations && (!playToEnd || move.terminalSamples === payload.iterations) &&
        Number.isFinite(move.equity) && Number.isFinite(move.win) && move.win >= 0 && move.win <= 1)) {
    throw new Error('Quackle returned incomplete simulation results.');
  }
  const simulatedMove = result.moves.find(move => candidateKey(move, grid) === key);
  if (!simulatedMove) throw new Error('Quackle did not return a simulation for this move.');
  return { ...evaluation, ...result, selected: simulatedMove,
    best: result.moves.reduce((top, move) => move.equity > top.equity ? move : top, simulatedMove) };
}

self.addEventListener('message', async event => {
  const { id, type, payload = {} } = event.data || {};
  try {
    const module = await getModule();
    let result;

    if (type === 'init') {
      result = { info: module.getEngineInfo() };
    } else if (type === 'evaluateMove' || type === 'simulateMove') {
      result = evaluateCustomMove(module, payload, type === 'simulateMove');
    } else if (type === 'simulateKibitz') {
      if (!Number.isInteger(payload.bagCount) || !Number.isInteger(payload.finalTurnsRemaining)) {
        throw new Error('Bag count and final-turn state must be integers');
      }
      result = simulate(module, payload);
    } else {
      throw new Error(`Unknown Quackle worker request: ${type}`);
    }

    self.postMessage({ id, result });
  } catch (error) {
    self.postMessage({
      id,
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : '',
    });
  }
});

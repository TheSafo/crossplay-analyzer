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

self.addEventListener('message', async event => {
  const { id, type, payload = {} } = event.data || {};
  try {
    const module = await getModule();
    let result;

    if (type === 'init') {
      result = { info: module.getEngineInfo() };
    } else if (type === 'kibitz') {
      result = module.kibitz(
        payload.gridJson,
        payload.rack,
        payload.playerScore,
        payload.opponentScore,
        payload.numMoves,
      );
    } else if (type === 'simulateKibitz') {
      if (!Number.isInteger(payload.bagCount) || !Number.isInteger(payload.finalTurnsRemaining)) {
        throw new Error('Bag count and final-turn state must be integers');
      }
      result = module.simulateKibitz(
        payload.gridJson,
        payload.rack,
        payload.playerScore,
        payload.opponentScore,
        payload.numMoves,
        payload.iterations,
        payload.bagCount,
        payload.finalTurnsRemaining,
      );
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

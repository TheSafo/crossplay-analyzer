const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const luck = require('./luck-analysis.js');

const emptyGrid = () => Array(15).fill('.'.repeat(15));
const turn = rack => ({ mine: true, rack, grid: emptyGrid() });
const frequencies = new Map([['cat', 4.5], ['qat', 2]]);
const wordForMove = (_, move) => move.word;
const opportunity = (moves, freq = frequencies) => luck.opportunityContext({}, moves, freq, wordForMove);

test('reference distribution matches the actual bundled Crossplay alphabet', () => {
  const alphabet = readFileSync(`${__dirname}/quackle.data`).subarray(0, 537).toString();
  const counts = {};
  for (const line of alphabet.split('\n')) {
    const fields = line.split(/\s+/);
    if (/^[A-Z]$/.test(fields[0])) counts[fields[0]] = Number(fields[3]);
    else if (fields[0] === 'blank') counts['?'] = Number(fields[2]);
  }
  assert.deepEqual(luck.TILE_COUNTS, counts);
  assert.equal(Object.values(counts).reduce((sum, count) => sum + count), 100);
});

test('flexible and blank racks outrank unbalanced racks with duplicates', () => {
  const tough = luck.rackFavorability(turn('EEIIUUV'));
  const flexible = luck.rackFavorability(turn('AEINRST'));
  const blank = luck.rackFavorability(turn('?AEINST'));
  assert.equal(tough.band, 'Tough');
  assert.equal(flexible.band, 'Favorable');
  assert.ok(blank.percentile > flexible.percentile);
  assert.ok(flexible.percentile > tough.percentile);
  assert.equal(blank.blanks, 1);
});

test('rack estimates are deterministic and independent of ordering and actual play', () => {
  const first = luck.rackFavorability(turn('?AEINST'));
  assert.deepEqual(luck.rackFavorability({ ...turn('TSNIEA?'), action: 'PASS 0', score: 0 }), first);
  assert.deepEqual(luck.rackFavorability({ ...turn('?AEINST'), action: 'SATINE 8H 80', score: 80 }), first);
});

test('sampling respects board depletion, short racks and physical blanks', () => {
  const physical = Object.entries(luck.TILE_COUNTS).flatMap(([tile, count]) => Array(count).fill(tile));
  // Leave only A and E off the board; every size-two sample must be AE.
  physical.splice(physical.indexOf('A'), 1);
  physical.splice(physical.indexOf('E'), 1);
  const board = physical.join('').replaceAll('?', 's').padEnd(225, '.');
  const grid = Array.from({ length: 15 }, (_, row) => board.slice(row * 15, (row + 1) * 15));
  assert.equal(luck.rackFavorability({ rack: 'AE', grid }).percentile, 50);
  assert.equal(luck.rackFavorability({ rack: 'A?', grid }), null);
  assert.equal(luck.rackFavorability({ rack: 'AA', grid }), null);
});

test('missing, malformed and physically impossible positions have no rack estimate', () => {
  for (const position of [null, {}, turn(''), turn('ABCDEFGH'), turn('KK'), turn('abc'),
    { rack: 'ABC', grid: ['.'] }, { rack: 'ABC', grid: Array(15).fill('!'.repeat(15)) }]) {
    assert.equal(luck.rackFavorability(position), null);
  }
});

test('missing a common opportunity costs more than a less-common opportunity', () => {
  const base = { category: 'mistake', loss: 10, playedEquity: 20 };
  const rack = { percentile: 50 };
  const common = luck.performance({ ...base, opportunity: opportunity([{ word: 'CAT', equity: 30 }]) }, rack);
  const uncommon = luck.performance({ ...base, opportunity: opportunity([{ word: 'QAT', equity: 30 }]) }, rack);
  assert.equal(common.adjustedLoss, 10);
  assert.equal(uncommon.adjustedLoss, 6);
  assert.ok(uncommon.adjusted > common.adjusted);
  // A common, nearly-as-good alternative remains a meaningful missed chance.
  const mixed = opportunity([{ word: 'QAT', equity: 30 }, { word: 'CAT', equity: 29 }]);
  assert.equal(luck.performance({ ...base, opportunity: mixed }, rack).adjustedLoss, 9);
});

test('unlisted words receive no rarity discount and loss never goes below zero', () => {
  const unknown = opportunity([{ word: 'UNLISTED', equity: 30 }]);
  assert.equal(unknown.bestWordZipf, null);
  assert.equal(unknown.knownCandidates, 0);
  assert.equal(unknown.accessibleEquity, 30);
  const point = { category: 'best', loss: 0, playedEquity: 30, opportunity: unknown };
  assert.equal(luck.performance(point, { percentile: 99 }).adjusted, 100);
  assert.equal(opportunity([{ word: 'QAT', equity: 30 }], new Map([['qat', -10]])).accessibleEquity, 24);
});

test('tough racks get more weight; opponent and unrated turns cannot inflate performance', () => {
  const review = { turns: [turn('EEIIUUV'), turn('?AEINST'), { ...turn('AEINRST'), mine: false }, turn('ACERSTU')] };
  const points = [
    { turnIndex: 0, category: 'best', loss: 0, playedEquity: 30, opportunity: opportunity([{ word: 'CAT', equity: 30 }]) },
    { turnIndex: 1, category: 'mistake', loss: 10, playedEquity: 20, opportunity: opportunity([{ word: 'CAT', equity: 30 }]) },
    { turnIndex: 2, category: 'best', loss: 0, playedEquity: 30, opportunity: opportunity([{ word: 'CAT', equity: 30 }]) },
    { turnIndex: 3, category: 'unrated', loss: null }
  ];
  const result = luck.summarize(review, points);
  assert.equal(result.turns.length, 3);
  assert.equal(result.rackCount, 3);
  assert.equal(result.ratedCount, 2);
  assert.equal(result.adjustedCount, 2);
  assert.equal(result.execution, 75);
  assert.ok(result.adjusted > result.execution);
  assert.equal(result.candidateWords, 2);
  const inverse = luck.summarize(review, points.map((point, index) => index < 2
    ? { ...point, loss: 10 - point.loss, playedEquity: 50 - point.playedEquity } : point));
  assert.ok(inverse.adjusted < inverse.execution);
});

test('legacy, partial and absent analysis do not imply perfect adjusted performance', () => {
  const review = { turns: [turn('AEINRST'), turn('INVALID')] };
  const none = luck.summarize(review);
  assert.equal(none.execution, null);
  assert.equal(none.adjusted, null);
  const legacy = luck.summarize(review, [{ turnIndex: 0, category: 'best', loss: 0 }]);
  assert.equal(legacy.execution, 100);
  assert.equal(legacy.adjustedCount, 0);
  assert.equal(legacy.adjusted, null);
  assert.equal(luck.performance({ category: 'unrated', loss: 0 }, { percentile: 50 }), null);
});

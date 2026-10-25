// A separate worker keeps long custom simulations cancellable without stopping
// the generated-move analysis or a whole-game review.
window.CustomMove = class CustomMove {
  constructor(container, getPosition, note = '') {
    this.getPosition = getPosition;
    this.token = 0;
    this.worker = null;
    this.pending = null;
    this.payload = null;
    this.root = document.createElement('section');
    this.root.className = 'custom-move';
    this.root.innerHTML = `
      <h3>Try a custom move</h3>
      <p class="custom-move-note"></p>
      <form class="custom-move-form">
        <label>Word<input name="word" aria-label="Custom move word" maxlength="15" placeholder="CAT" autocomplete="off" spellcheck="false" autocapitalize="off" required></label>
        <label>Start square<input name="square" aria-label="Custom move start square" maxlength="3" placeholder="G8" autocomplete="off" spellcheck="false" required></label>
        <label>Direction<select name="direction" aria-label="Custom move direction"><option value="across">Across →</option><option value="down">Down ↓</option></select></label>
        <button type="submit">Evaluate move</button>
      </form>
      <p class="custom-move-help">Include existing letters, or use . for them. Use uppercase for regular tiles and lowercase for blanks (e.g. CAt).</p>
      <div class="custom-move-status" role="status" aria-live="polite"></div>
      <button type="button" class="custom-move-cancel" hidden>Cancel evaluation</button>
      <div class="custom-move-result"></div>`;
    this.root.querySelector('.custom-move-note').textContent = note ||
      'Evaluate a move even when it is outside Quackle’s suggested moves.';
    this.form = this.root.querySelector('form');
    this.status = this.root.querySelector('.custom-move-status');
    this.output = this.root.querySelector('.custom-move-result');
    this.cancelButton = this.root.querySelector('.custom-move-cancel');
    this.form.addEventListener('submit', event => {
      event.preventDefault();
      this.evaluate(false);
    });
    this.form.addEventListener('input', () => this.reset());
    this.cancelButton.addEventListener('click', () => {
      this.stop();
      this.status.textContent = 'Evaluation cancelled.';
    });
    container.append(this.root);
  }

  setBusy(busy) {
    for (const input of this.form.elements) input.disabled = busy;
    this.cancelButton.hidden = !busy;
    const simulate = this.output.querySelector('button');
    if (simulate) simulate.disabled = busy;
    this.root.setAttribute('aria-busy', String(busy));
  }

  stop() {
    this.token++;
    if (this.worker) this.worker.terminate();
    this.worker = null;
    if (this.pending) this.pending.reject(new Error('Evaluation cancelled.'));
    this.pending = null;
    this.setBusy(false);
  }

  reset() {
    this.stop();
    this.payload = null;
    this.output.replaceChildren();
    this.status.textContent = '';
  }

  dispose() {
    this.stop();
    this.root.remove();
  }

  request(type, payload) {
    if (!this.worker) {
      const worker = new Worker('quackle-worker.js');
      this.worker = worker;
      worker.addEventListener('message', event => {
        if (this.worker !== worker || !this.pending || this.pending.id !== event.data.id) return;
        const pending = this.pending;
        this.pending = null;
        if (event.data.error) pending.reject(new Error(event.data.error));
        else pending.resolve(event.data.result);
      });
      worker.addEventListener('error', () => {
        if (this.worker !== worker) return;
        if (this.pending) this.pending.reject(new Error('The engine failed to load. Try again.'));
        this.pending = null;
        this.worker.terminate();
        this.worker = null;
      });
    }
    return new Promise((resolve, reject) => {
      const id = this.token;
      this.pending = { id, resolve, reject };
      this.worker.postMessage({ id, type, payload });
    });
  }

  async evaluate(simulateWin) {
    const token = ++this.token;
    this.setBusy(true);
    this.status.classList.remove('custom-move-error');
    this.status.textContent = simulateWin
      ? 'Estimating win chances… Moves farther down the ranking take longer. You can cancel.'
      : 'Checking the move and evaluating all legal alternatives…';
    if (!simulateWin) this.output.replaceChildren();
    try {
      if (!simulateWin) {
        const position = this.getPosition();
        if (!position) throw new Error('Analyze a board first.');
        this.payload = { ...position, iterations: 277, customMove: {
          word: this.form.elements.word.value.trim(),
          square: this.form.elements.square.value.trim(),
          direction: this.form.elements.direction.value
        } };
      }
      const result = await this.request(simulateWin ? 'simulateMove' : 'evaluateMove', this.payload);
      if (token !== this.token) return;
      this.renderResult(result);
      this.status.textContent = simulateWin ? 'Win simulation complete.' : 'Move evaluated.';
    } catch (error) {
      if (token !== this.token) return;
      this.status.classList.add('custom-move-error');
      this.status.textContent = error.message;
    } finally {
      if (token === this.token) this.setBusy(false);
    }
  }

  renderResult(result) {
    this.output.replaceChildren();
    const append = (parent, tag, text, className = '') => {
      const element = document.createElement(tag);
      element.textContent = text;
      element.className = className;
      parent.append(element);
      return element;
    };
    const table = document.createElement('table');
    const head = table.createTHead().insertRow();
    const labels = ['Move', 'Score', 'Leave', result.simulated ? 'Sim. equity' : 'Static equity'];
    if (result.simulated) labels.push('Win%');
    for (const label of labels) append(head, 'th', label);
    const body = table.createTBody();
    for (const [label, move] of [['Your move', result.selected], ['Best compared move', result.best]]) {
      const row = body.insertRow();
      append(row, 'td', label + ': ' + (move.position ? move.position + ' ' : '') + move.tiles);
      append(row, 'td', move.score);
      append(row, 'td', move.leave || '—');
      append(row, 'td', move.equity.toFixed(1));
      if (result.simulated) append(row, 'td', (move.win * 100).toFixed(1) + '%');
    }
    this.output.append(table);
    const loss = Math.max(0, result.best.equity - result.selected.equity);
    append(this.output, 'p', loss.toFixed(1) + ' equity points behind the best compared move.', 'custom-move-comparison');
    append(this.output, 'p', 'Static rank #' + result.staticRank + ' of ' + result.legalMoveCount + ' legal moves.', 'custom-move-help');
    if (result.simulated) {
      append(this.output, 'p', 'Compared ' + result.candidateCount + ' moves with ' + result.iterationsCompleted +
        ' samples each. ' + (result.playToEnd ? 'Samples follow Crossplay’s final-turn rules to the finish.' :
          'Win chances use Quackle’s two-ply estimate.'), 'custom-move-help');
    } else {
      append(this.output, 'p', 'Static equity evaluates score and rack leave without a win simulation.', 'custom-move-help');
      const button = append(this.output, 'button', 'Estimate win% (slower)');
      button.type = 'button';
      button.addEventListener('click', () => this.evaluate(true));
    }
  }
};

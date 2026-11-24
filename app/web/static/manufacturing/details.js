window.manufacturingFeatures.push(() => ({
  historyData: null,
  historyLoading: false,
  historyError: '',
  historyHoverText: '',
  materialNames: {},
  materialNamesLoading: false,
  materialNamesMessage: '',
  preparingMarket: false,
  preparationMessage: '',
  selected: null,
  invention: null,
  inventionMessage: '',
  inventionLoading: false,
  inventionChecking: false,
  lastInventionCheck: null,
  detailSequence: 0,
  returnFocus: null,
  closeItem() {
    const target = this.returnFocus;
    this.selected = null;
    this.detailSequence++;
    this.returnFocus = null;
    document.body.style.overflow = '';
    this.$nextTick(() => {
      if (target?.isConnected && !this.selected) target.focus();
    });
  },
  trapDialog(event) {
    const nodes = [...this.$refs.dialog.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),[tabindex="0"]')].filter(n => n.getClientRects().length);
    const first = nodes[0],
      last = nodes.at(-1);
    if (!first) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey && (document.activeElement === first || document.activeElement === this.$refs.dialog)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === this.$refs.dialog)) {
      event.preventDefault();
      first.focus();
    }
  },
  async openItem(item) {
    this.returnFocus = document.activeElement;
    document.body.style.overflow = 'hidden';
    this.selected = item;
    this.invention = null;
    this.inventionMessage = '';
    this.inventionChecking = false;
    this.inventionLoading = false;
    this.lastInventionCheck = null;
    this.detailSequence++;
    await this.$nextTick();
    await new Promise(resolve => requestAnimationFrame(resolve));
    if (this.selected?.type_id !== item.type_id) return;
    (this.$refs.dialog.querySelector('button:not([disabled])') || this.$refs.dialog).focus();
    await Promise.allSettled([this.loadHistory(), this.loadMaterialNames(), item.invention_required && !this.demo ? this.loadInvention() : Promise.resolve()]);
  },
  async loadHistory() {
    if (!this.selected) return;
    const seq = this.detailSequence,
      id = this.selected.type_id;
    this.historyData = null;
    this.historyError = '';
    this.historyHoverText = '';
    this.historyLoading = true;
    try {
      const data = this.demo ? {
        stale: false,
        days: Array.from({
          length: Number(this.resultForm.days)
        }, (_, i) => ({
          date: new Date(Math.floor(Date.now() / 86400000) * 86400000 - (Number(this.resultForm.days) - i) * 86400000).toISOString().slice(0, 10),
          average: String(100000 + i * 1000 + Math.sin(i) * 5000),
          volume: 100 + i * 3
        }))
      } : await this.api('/api/v1/market/history/' + id + '?' + new URLSearchParams({
        hub_id: this.resultForm.hub_id,
        days: this.resultForm.days
      }));
      if (seq !== this.detailSequence) return;
      this.historyData = {
        ...data,
        days: [...data.days].sort((a, b) => a.date.localeCompare(b.date))
      };
    } catch (_) {
      if (seq === this.detailSequence) this.historyError = 'Trading history could not be loaded. Your cost calculations are still available.';
    } finally {
      if (seq === this.detailSequence) this.historyLoading = false;
    }
  },
  materialName(id) {
    return this.materialNames[id] || (this.materialNamesLoading ? 'Loading name...' : 'Name unavailable');
  },
  async loadMaterialNames() {
    const seq = this.detailSequence;
    const ids = [...new Set((this.selected?.materials || (this.calculator ? this.page.items[0]?.materials : []) || []).map(m => m.type_id))].filter(id => !this.materialNames[id]);
    this.materialNamesMessage = '';
    if (this.demo) {
      this.materialNames = {
        ...this.materialNames,
        34: 'Tritanium'
      };
      return;
    }
    if (!ids.length) return;
    this.materialNamesLoading = true;
    try {
      const params = new URLSearchParams();
      ids.forEach(id => params.append('type_ids', id));
      const result = await this.api('/api/v1/catalog/names?' + params);
      this.materialNames = {
        ...this.materialNames,
        ...result.names
      };
      if (seq === this.detailSequence && result.missing_type_ids.length) this.materialNamesMessage = 'Some material names are unavailable. Quantities and prices are still shown.';
    } catch (_) {
      if (seq === this.detailSequence) this.materialNamesMessage = 'Material names could not be loaded. Quantities and prices are still shown. Try again.';
    } finally {
      if (seq === this.detailSequence) this.materialNamesLoading = false;
    }
  },
  inventionStatus(view) {
    if (!view?.request) return 'No calculation is prepared for this market and pricing choice. Select Prepare calculation to queue it.';
    const messages = {
      pending: 'Queued for background calculation. Select Check status to see when it is ready.',
      ready: 'Calculation ready. Compare the estimated cost per manufactured unit below.',
      missing_prices: 'Some datacore or decryptor prices are missing. Only fully priced alternatives can be compared.',
      unsupported: 'No supported invention route was found for this item.',
      error: 'The last calculation failed. Select Prepare calculation to retry.'
    };
    return (messages[view.request.status] || 'Calculation status is unavailable.') + (view.stale ? ' This saved valuation is due for its daily update.' : '') + (view.request.result && !view.request.result.complete_pricing ? ' Some alternatives have missing prices.' : '');
  },
  async prepareMarketInvention() {
    if (this.demo || this.preparingMarket) return;
    this.preparingMarket = true;
    this.preparationMessage = '';
    try {
      await this.api((this.calculator ? '/api/v1/invention/' + this.appliedBlueprintId + '/prepare' : '/api/v1/invention/prepare') + '?' + this.inventionParams(), {
        method: 'POST'
      });
      this.preparationMessage = 'Invention preparation queued for this material market and pricing choice. Select Show results after the background calculation finishes.';
    } catch (_) {
      this.preparationMessage = 'Could not request invention preparation. Please try again.';
    } finally {
      this.preparingMarket = false;
    }
  },
  inventionParams() {
    return new URLSearchParams({
      hub_id: this.resultForm.material_hub_id || this.resultForm.hub_id,
      order_type: this.resultForm.material_order_type
    });
  },
  get inventionReady() {
    return this.invention?.request?.status === 'ready' && !this.invention.stale;
  },
  timeLabel(value) {
    if (!value) return 'Not available';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Not available' : new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZoneName: 'short'
    }).format(date);
  },
  async loadInvention() {
    if (!this.selected || this.demo || this.inventionChecking) return;
    const id = this.selected.type_id,
      seq = this.detailSequence;
    this.inventionChecking = true;
    this.inventionMessage = 'Checking saved calculation...';
    try {
      const data = await this.api(`/api/v1/invention/${id}?${this.inventionParams()}`);
      if (seq !== this.detailSequence || this.selected?.type_id !== id) return;
      this.invention = data;
      this.lastInventionCheck = new Date().toISOString();
      this.inventionMessage = 'Status checked. ' + this.inventionStatus(data);
    } catch (_) {
      if (seq === this.detailSequence) this.inventionMessage = 'Could not check calculation status. Please try again.';
    } finally {
      if (seq === this.detailSequence) this.inventionChecking = false;
    }
  },
  async prepareInvention() {
    if (!this.selected || this.demo || this.inventionLoading || this.inventionChecking) return;
    const id = this.selected.type_id,
      seq = this.detailSequence;
    this.inventionLoading = true;
    this.inventionMessage = 'Requesting a background calculation...';
    try {
      const data = await this.api(`/api/v1/invention/${id}/prepare?${this.inventionParams()}`, {
        method: 'POST'
      });
      if (seq !== this.detailSequence || this.selected?.type_id !== id) return;
      this.invention = data;
      this.lastInventionCheck = new Date().toISOString();
      this.inventionMessage = data.queued ? 'Calculation queued. Select Check status to follow its progress.' : data.request?.status === 'ready' && !data.stale ? 'This calculation is already prepared and current. The saved daily result is being reused; no extra job was created.' : data.request?.status === 'unsupported' ? 'No supported invention route is available.' : 'Preparation is already pending or queued. Select Check status to follow its progress.';
    } catch (_) {
      if (seq === this.detailSequence) this.inventionMessage = 'Could not request calculation preparation. Please try again.';
    } finally {
      if (seq === this.detailSequence) this.inventionLoading = false;
    }
  },
}));

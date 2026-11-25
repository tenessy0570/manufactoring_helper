window.createProductionEstimates = () => ({
  estimateUnits: '',
  estimateRuns: '',
  hub: 'jita',
  side: 'sell',
  buyBroker: '0',
  facilityTax: '0',
  systemIndex: '0',
  estimateNote: '',
  decryptorChoice: 'best',
  inventionOptions: [],
  optionsLoading: false,
  optionsError: '',
  optionsSequence: 0,
  optionsTimer: null,
  resetEstimate() {
    clearTimeout(this.optionsTimer);
    this.optionsSequence++;
    this.estimateNote = '';
    this.decryptorChoice = 'best';
    this.inventionOptions = [];
    this.optionsError = '';
    this.optionsLoading = false;
    if (this.selected && this.entry.kind === 'invention' && Number.isInteger(Number(this.estimateUnits)) && Number(this.estimateUnits) > 0 && Number(this.estimateUnits) <= 1000000000) {
      this.optionsLoading = true;
      this.optionsTimer = setTimeout(() => this.loadDecryptors(), window.eveConfig.searchDebounceMs);
    }
  },
  get selectedDecryptor() {
    return this.inventionOptions.find(option => (option.decryptor_id === null ? 'none' : String(option.decryptor_id)) === this.decryptorChoice);
  },
  async loadDecryptors() {
    const seq = this.optionsSequence,
      id = this.selected?.id,
      units = Number(this.estimateUnits),
      hub = this.hub;
    if (!id || this.entry.kind !== 'invention') return;
    try {
      const result = await this.requestApi('/' + id + '/estimate', 'POST', {
        kind: 'invention',
        units,
        hub_id: hub,
        decryptor_id: 'best'
      });
      if (seq !== this.optionsSequence || id !== this.selected?.id || units !== Number(this.estimateUnits) || hub !== this.hub || this.entry.kind !== 'invention') return;
      this.inventionOptions = result.decryptor_options || [];
      const best = this.inventionOptions.find(option => option.is_best);
      this.decryptorChoice = best ? (best.decryptor_id === null ? 'none' : String(best.decryptor_id)) : 'best';
      if (!best) this.optionsError = 'No priced decryptor options are available.';
    } catch (error) {
      if (seq === this.optionsSequence) this.optionsError = error.message;
    } finally {
      if (seq === this.optionsSequence) this.optionsLoading = false;
    }
  },
  async estimate() {
    await this.action(async () => {
      const result = await this.requestApi('/' + this.selected.id + '/estimate', 'POST', {
        kind: this.entry.kind,
        decryptor_id: this.decryptorChoice === 'best' ? 'best' : this.decryptorChoice === 'none' ? null : Number(this.decryptorChoice),
        ...(this.entry.kind !== 'invention' && this.estimateRuns ? {
          manufacturing_runs: Number(this.estimateRuns)
        } : {
          units: Number(this.estimateUnits)
        }),
        hub_id: this.hub,
        material_order_type: this.side,
        buy_broker_fee: this.buyBroker || '0',
        facility_tax: this.facilityTax || '0',
        system_cost_index: this.systemIndex || '0'
      });
      this.entry.amount = result.amount;
      this.inventionOptions = result.decryptor_options || [];
      this.estimateNote = result.description + (result.stale ? ' Saved data is due for refresh.' : '') + (!result.complete_comparison ? ' Some invention options have missing prices.' : '');
      this.message = 'Estimate inserted. Review the amount, then save.';
    });
  },
});

document.addEventListener('alpine:init', () => {
  Alpine.data('productionApp', () => ({
    items: [],
    offset: 0,
    selected: null,
    creating: false,
    busy: false,
    error: '',
    message: '',
    searchText: '',
    typeId: null,
    matches: [],
    searchSequence: 0,
    activeMatch: -1,
    suggestionsOpen: false,
    details: {
      units: '',
      comment: '',
      status: 'in_progress'
    },
    entry: {
      kind: 'invention',
      amount: '',
      comment: ''
    },
    editingId: null,
    estimateUnits: '',
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
    async init() {
      for (const field of ['selected?.id', 'entry.kind', 'estimateUnits', 'hub']) this.$watch(field, () => this.resetEstimate());
      await this.load();
    },
    money(value) {
      return value === null || value === undefined ? 'Not recorded' : Number(value).toLocaleString('en-US', {
        maximumFractionDigits: 2
      });
    },
    label(kind) {
      return {
        invention: 'Invention',
        materials: 'Materials',
        manufacturing: 'Manufacturing',
        income: 'Income'
      } [kind];
    },
    async api(path = '', method = 'GET', data) {
      const r = await fetch('/api/v1/productions' + path, {
        method,
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        ...(data === undefined ? {} : {
          body: JSON.stringify(data)
        })
      });
      if (r.status === 401) {
        location.assign('/login');
        throw Error('Please log in again.');
      }
      if (r.status === 204) return null;
      const body = await window.readApiResponse(r);
      if (!r.ok) throw Error(typeof body.detail === 'string' ? body.detail : 'Check the entered values. Amounts must be positive or zero with at most two decimals.');
      return body;
    },
    async action(work) {
      if (this.busy) return;
      this.busy = true;
      this.error = '';
      this.message = '';
      try {
        await work();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },
    async load(offset = 0) {
      await this.action(async () => {
        const rows = await this.api('?' + new URLSearchParams({
          offset,
          limit: 50
        }));
        this.items = rows;
        this.offset = offset;
      });
    },
    startCreate() {
      this.selected = null;
      this.creating = true;
      this.typeId = null;
      this.searchText = '';
      this.matches = [];
      this.details = {
        units: '',
        comment: '',
        status: 'in_progress'
      };
      this.error = '';
    },
    async open(item) {
      await this.action(async () => {
        this.select(await this.api('/' + item.id));
      });
    },
    select(item) {
      this.selected = item;
      this.creating = false;
      this.details = {
        units: item.units ?? '',
        comment: item.comment,
        status: item.status
      };
      this.estimateUnits = item.units ?? '';
      this.resetEntry();
    },
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
        const result = await this.api('/' + id + '/estimate', 'POST', {
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
    resetEntry(kind = 'invention') {
      this.entry = {
        kind,
        amount: '',
        comment: ''
      };
      this.editingId = null;
      this.resetEstimate();
    },
    invalidate() {
      this.typeId = null;
      this.matches = [];
      this.activeMatch = -1;
      this.suggestionsOpen = true;
      this.searchSequence++;
    },
    async search() {
      const seq = ++this.searchSequence;
      const text = this.searchText.trim().replace(/\s+blueprint$/i, '');
      if (this.typeId || text.length < 2) return;
      try {
        const r = await fetch('/api/v1/catalog/items?' + new URLSearchParams({
          search: text,
          limit: 50
        }), {
          credentials: 'same-origin'
        });
        if (r.status === 401) {
          location.assign('/login');
          return;
        }
        if (!r.ok) throw Error('Search unavailable. Retry.');
        const data = await window.readApiResponse(r);
        if (seq === this.searchSequence) this.matches = data.items;
      } catch (e) {
        if (seq === this.searchSequence) this.error = e.message;
      }
    },
    choose(item) {
      this.searchSequence++;
      this.typeId = item.type_id;
      this.searchText = item.name;
      this.suggestionsOpen = false;
    },
    searchKey(event) {
      if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
        event.preventDefault();
        this.suggestionsOpen = true;
        this.activeMatch = event.key === 'ArrowDown' ? Math.min(this.matches.length - 1, this.activeMatch + 1) : Math.max(0, this.activeMatch - 1);
        this.$nextTick(() => document.getElementById('production-option-' + this.activeMatch)?.scrollIntoView({
          block: 'nearest'
        }));
      } else if (event.key === 'Enter' && this.suggestionsOpen && this.matches.length) {
        event.preventDefault();
        this.choose(this.matches[Math.max(this.activeMatch, 0)]);
      } else if (['Escape', 'Tab'].includes(event.key)) this.suggestionsOpen = false;
    },
    detailsPayload() {
      return {
        ...this.details,
        units: this.details.units === '' ? null : Number(this.details.units)
      };
    },
    async create() {
      if (!this.typeId) {
        this.error = 'Choose a product from the suggestions.';
        return;
      }
      await this.action(async () => {
        const item = await this.api('', 'POST', {
          ...this.detailsPayload(),
          type_id: this.typeId
        });
        this.select(item);
        this.items = this.offset === 0 ? [item, ...this.items].slice(0, 50) : [item];
        this.offset = 0;
        this.message = 'Production created. Add expenses whenever you are ready.';
        try {
          this.items = await this.api('?offset=0&limit=50');
        } catch (_) {
          this.message = 'Production created. Refresh the history list to load the remaining batches.';
        }
      });
    },
    replace(item) {
      this.selected = item;
      this.items = this.items.map(row => row.id === item.id ? item : row);
    },
    async saveDetails() {
      await this.action(async () => {
        this.replace(await this.api('/' + this.selected.id, 'PUT', this.detailsPayload()));
        this.message = 'Production updated. Existing expenses are unchanged.';
      });
    },
    async saveEntry() {
      await this.action(async () => {
        const path = '/' + this.selected.id + '/entries' + (this.editingId ? '/' + this.editingId : '');
        this.replace(await this.api(path, this.editingId ? 'PUT' : 'POST', this.entry));
        const kind = this.entry.kind;
        this.resetEntry(kind);
        this.message = kind === 'income' ? 'Income added to total revenue.' : 'Expense saved.';
      });
    },
    editEntry(item) {
      this.editingId = item.id;
      this.entry = {
        kind: item.kind,
        amount: item.amount,
        comment: item.comment
      };
      this.resetEstimate();
      this.$nextTick(() => this.$refs.amount.focus());
    },
    async removeEntry(item) {
      if (!confirm('Delete this entry? Totals will be recalculated.')) return;
      await this.action(async () => {
        this.replace(await this.api('/' + this.selected.id + '/entries/' + item.id, 'DELETE'));
        if (this.editingId === item.id) this.resetEntry();
        this.message = 'Entry deleted.';
      });
    },
    async removeProduction() {
      if (!confirm('Delete production: ' + this.selected.name + '? All recorded expenses and income will be permanently deleted.')) return;
      await this.action(async () => {
        const id = this.selected.id;
        await this.api('/' + id, 'DELETE');
        this.items = this.items.filter(item => item.id !== id);
        this.selected = null;
        this.message = 'Production deleted.';
      });
    },
    async estimate() {
      await this.action(async () => {
        const result = await this.api('/' + this.selected.id + '/estimate', 'POST', {
          kind: this.entry.kind,
          decryptor_id: this.decryptorChoice === 'best' ? 'best' : this.decryptorChoice === 'none' ? null : Number(this.decryptorChoice),
          units: Number(this.estimateUnits),
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
  }));
});

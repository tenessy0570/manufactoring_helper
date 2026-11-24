document.addEventListener('alpine:init', () => {
  Alpine.data('productionApp', () => window.composePage({
    items: [],
    offset: 0,
    selected: null,
    creating: false,
    busy: false,
    error: '',
    message: '',
    details: {
      units: '',
      actual_units: '',
      actual_runs: '',
      comment: '',
      status: 'in_progress'
    },
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
        actual_units: '',
        actual_runs: '',
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
        actual_units: item.actual_units ?? '',
        actual_runs: item.actual_runs ?? '',
        comment: item.comment,
        status: item.status
      };
      this.estimateUnits = item.units ?? '';
      this.estimateRuns = '';
      this.purchaseText = '';
      this.purchaseNote = '';
      this.resetEntry();
    },
    detailsPayload() {
      return {
        ...this.details,
        units: this.details.units === '' ? null : Number(this.details.units),
        actual_units: this.details.actual_units === '' ? null : Number(this.details.actual_units),
        actual_runs: this.details.actual_runs === '' ? null : Number(this.details.actual_runs)
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
  }, [window.productionBlueprint, window.productionEstimates, window.productionEntries, window.productionPurchases]));
});

document.addEventListener('alpine:init', () => {
  Alpine.data('tradingApp', () => window.composePage({
    hubs: ['jita', 'amarr', 'dodixie', 'rens', 'hek'],
    form: {},
    applied: null,
    page: null,
    loading: false,
    error: '',
    storageWarning: '',
    sequence: 0,
    now: Date.now(),
    timer: null,
    getDefaultSettings() {
      return {
        filter_daily_turnover: false,
        price_spikes_only: false,
        price_spike_threshold: '30',
        route_mode: 'safe',
        max_jumps: '',
        min_profit_per_jump: '',
        source_hub: '',
        destination_hub: '',
        purchase_side: 'sell',
        sale_side: 'buy',
        search: '',
        buy_broker_fee: '0',
        sell_broker_fee: '0',
        sales_tax: '0',
        sell_price_range: '5',
        buy_price_range: '5',
        history_days: '30',
        min_daily_isk_volume: '',
        min_profit: '',
        min_margin: '',
        min_batch_profit: '',
        max_investment: '',
        max_cargo_m3: '',
        max_units: '',
        fresh_only: false,
        rank_by: 'batch_profit',
        limit: '25'
      };
    },
    async init() {
      this.form = this.getDefaultSettings();
      try {
        const saved = JSON.parse(localStorage.getItem('eve.interhub.settings.v2') || localStorage.getItem('eve.interhub.settings.v1'));
        if (saved && typeof saved === 'object' && !Array.isArray(saved))
          for (const key of Object.keys(this.form)) {
            const value = saved[key];
            if (typeof this.form[key] === 'boolean' ? typeof value === 'boolean' : ['string', 'number'].includes(typeof value)) this.form[key] = value;
          }
        if (!localStorage.getItem('eve.interhub.settings.v2')) {
          this.form.source_hub = '';
          this.form.destination_hub = '';
        }
      } catch (_) {}
      this.readProfiles();
      this.restoreColumns();
      this.$watch('hiddenColumns', () => this.saveColumns());
      this.$watch('form', () => this.save());
      this.timer = setInterval(() => this.now = Date.now(), window.eveConfig.clockTickMs);
      await this.load();
    },
    formatFullMoney(value) {
      return this.formatMoney(value);
    },
    compactMoney(value) {
      if (value === null || value === undefined) return '--';
      return new Intl.NumberFormat('en-US', {
        notation: 'compact',
        maximumFractionDigits: 2
      }).format(Number(value));
    },
    destroy() {
      clearInterval(this.timer);
    },
    save() {
      try {
        localStorage.setItem('eve.interhub.settings.v2', JSON.stringify(this.form));
      } catch (_) {
        this.storageWarning = 'Browser storage is unavailable. Settings may not survive a reload.';
      }
    },
    get changed() {
      return this.applied && JSON.stringify(this.form) !== JSON.stringify(this.applied);
    },
    get resultForm() {
      return this.applied || this.form;
    },
    swap() {
      const hub = this.form.source_hub;
      this.form.source_hub = this.form.destination_hub;
      this.form.destination_hub = hub;
    },
    formatMoney(value) {
      if (value === null || value === undefined) return '--';
      return new Intl.NumberFormat('en-US', {
        maximumFractionDigits: 2
      }).format(Number(value));
    },
    formatPercent(value) {
      return Number(value).toFixed(1) + '%';
    },
    getHubName(hub) {
      return hub ? hub.charAt(0).toUpperCase() + hub.slice(1) : 'All hubs';
    },
    formatAge(stamp) {
      if (!stamp) return 'not loaded';
      const m = Math.floor(Math.max(0, this.now - Date.parse(stamp)) / 60000);
      return m < 1 ? '<1m' : (m >= 1440 ? Math.floor(m / 1440) + 'd ' : '') + Math.floor(m % 1440 / 60) + 'h ' + m % 60 + 'm';
    },
    stale(item) {
      return item.stale || [item.source_updated_at, item.destination_updated_at].some(stamp => Date.parse(stamp) + window.eveConfig.marketFreshnessMs <= this.now);
    },
    async load(offset = 0, useApplied = false) {
      const form = JSON.parse(JSON.stringify(useApplied && this.applied ? this.applied : this.form));
      if (form.source_hub && form.source_hub === form.destination_hub) {
        this.error = 'Choose two different hubs.';
        return;
      }
      const seq = ++this.sequence;
      this.loading = true;
      this.error = '';
      this.save();
      try {
        const params = new URLSearchParams({
          offset: String(offset)
        });
        for (const [key, value] of Object.entries(form))
          if (value !== '' && value !== null) params.set(key, String(value));
        const response = await fetch('/api/v1/trading/opportunities?' + params, {
          credentials: 'same-origin'
        });
        if (response.status === 401) {
          location.assign('/login');
          throw Error('Your session expired.');
        }
        const data = await window.readApiResponse(response);
        if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? data.detail.map(e => e.loc.at(-1) + ': ' + e.msg).join('; ') : 'Could not load trading opportunities.');
        if (seq !== this.sequence) return;
        this.page = data;
        this.applied = form;
      } catch (error) {
        if (seq === this.sequence) this.error = error.message;
      } finally {
        if (seq === this.sequence) this.loading = false;
      }
    }
  }, [window.createTradingProfiles, window.createTradingHistory, window.createTradingColumns]));
});

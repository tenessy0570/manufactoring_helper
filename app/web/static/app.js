/* Local application state; all monetary calculations remain on the server. */
document.addEventListener('alpine:init', () => {
  Alpine.data('manufacturingApp', () => window.composeManufacturing({
    ...window.marketHistoryChartMethods,
    calculator: document.body.dataset.calculator === 'true',
    demo: new URLSearchParams(location.search).get('demo') === '1',
    loading: false,
    filtersOpen: true,
    error: '',
    storageWarning: '',
    requestSequence: 0,
    appliedForm: null,
    appliedSettings: {},
    hubs: [{
      id: 'jita',
      name: 'Jita'
    }, {
      id: 'amarr',
      name: 'Amarr'
    }, {
      id: 'dodixie',
      name: 'Dodixie'
    }, {
      id: 'rens',
      name: 'Rens'
    }, {
      id: 'hek',
      name: 'Hek'
    }],
    progressNow: Date.now(),
    isStale(item) {
      return !!item && (item.stale || (!!item.fresh_until && Date.parse(item.fresh_until) <= this.progressNow));
    },
    staleExplanation(item) {
      const labels = {
        recipe: 'Manufacturing recipe',
        product_market: 'Product market prices',
        material_market: 'Material market prices',
        history: 'Regional trading history',
        invention: 'Invention estimate'
      };
      const sources = Object.entries(item?.freshness_deadlines || {}).filter(([, date]) => Date.parse(date) <= this.progressNow).map(([key]) => labels[key] || key);
      return sources.length ? 'Due for refresh: ' + sources.join(', ') + '. Select ' + (this.calculator ? 'Calculate profit' : 'Show results') + ' after the background update.' : 'Saved inputs are due for refresh. Select ' + (this.calculator ? 'Calculate profit' : 'Show results') + ' after the background update.';
    },
    formatRelativeTime(value) {
      if (!value) return 'not yet loaded';
      const stamp = new Date(value).getTime();
      if (!Number.isFinite(stamp)) return 'not available';
      const minutes = Math.floor(Math.max(0, this.progressNow - stamp) / 60000);
      return minutes < 1 ? 'less than a minute ago' : (minutes >= 1440 ? Math.floor(minutes / 1440) + 'd ' : '') + Math.floor(minutes % 1440 / 60) + 'h ' + minutes % 60 + 'm ago';
    },
    dataProgress: null,
    progressError: false,
    progressSequence: 0,
    async loadProgress() {
      if (this.demo) return;
      const seq = ++this.progressSequence;
      try {
        const result = await this.requestApi('/health/data-progress?hub=' + this.resultForm.hub_id);
        if (seq !== this.progressSequence) return;
        this.dataProgress = result;
        this.progressError = false;
      } catch (_) {
        if (seq === this.progressSequence) this.progressError = true;
      }
    },
    hiddenColumns: [],
    columnOptions: [{
      id: 'cost',
      label: 'Cost / unit'
    }, {
      id: 'profit',
      label: 'Profit / unit'
    }, {
      id: 'demand',
      label: 'Profit on demand'
    }, {
      id: 'margin',
      label: 'Margin'
    }, {
      id: 'daily',
      label: 'Profit / day'
    }, {
      id: 'bpcTime',
      label: 'Production time / T2 BPC'
    }, {
      id: 'priceChange',
      label: 'Price vs history (%)'
    }, {
      id: 'volumeShare',
      label: 'Daily volume share'
    }, {
      id: 'turnover',
      label: 'Regional turnover / day'
    }, {
      id: 'data',
      label: 'Data freshness'
    }],
    isColumnVisible(id) {
      return !this.hiddenColumns.includes(id);
    },
    form: {},
    page: {
      items: [],
      total: 0,
      offset: 0,
      limit: 25
    },
    getDefaultSettings() {
      return {
        search: '',
        hub_id: 'jita',
        material_hub_id: '',
        tech: '',
        category: '',
        material_order_type: 'sell',
        product_order_type: 'sell',
        buy_demand_tolerance_pct: '5',
        min_profit: '',
        min_margin: '',
        max_price_increase_pct: '',
        max_daily_volume_share_pct: '',
        min_daily_isk_volume: '',
        include_copying_time: false,
        include_invention_time: false,
        invention_slots: '1',
        manufacturing_runs: '1',
        production_lines: '1',
        days: '30',
        sales_tax: '0',
        buy_broker_fee: '0',
        sell_broker_fee: '0',
        facility_tax: '0',
        system_cost_index: '0',
        min_product_volume: '',
        include_invention_cost: false,
        fresh_only: false,
        require_full_run_demand: false,
        rank_by: 'profit_per_day',
        limit: '25'
      };
    },
    async init() {
      this.form = this.getDefaultSettings();
      if (!this.calculator) await this.readExclusions();
      this.profiles = this.readBrowserProfiles();
      const restored = this.restoreSettings();
      this.$watch('hiddenColumns', () => this.saveSettings());
      this.$watch('form', () => this.saveSettings());
      this.$watch('filtersOpen', () => this.saveSettings());
      this.$watch('blueprint', () => this.saveSettings());
      window.addEventListener('pagehide', () => this.saveSettings());
      const initialForm = JSON.stringify(this.form);
      if (!this.demo) {
        try {
          const result = await this.requestApi('/api/v1/profiles');
          this.profiles = [...this.profiles, ...result.items];
          if (restored) {
            if (!this.profiles.some(p => p.id === this.profileId)) this.profileId = '';
          } else if (!this.calculator && JSON.stringify(this.form) === initialForm) {
            const chosen = this.profiles.find(p => p.is_default);
            if (chosen) {
              this.profileId = chosen.id;
              this.setProfile(chosen);
            }
          }
        } catch (_) {
          this.profileWarning = 'Server profiles could not be loaded. Browser profiles and custom filters are still available.';
        }
      }
      if (!this.calculator || this.blueprint.type_id) await this.load();
    },
    fieldLabel(field) {
      const labels = {
        min_profit: 'Minimum profit per unit',
        min_margin: 'Minimum margin',
        max_price_increase_pct: 'Maximum price increase',
        max_daily_volume_share_pct: 'Maximum daily volume share',
        min_daily_isk_volume: 'Minimum regional turnover',
        min_product_volume: 'Minimum volume at the selected price',
        days: 'History period',
        sales_tax: 'Sales tax',
        buy_broker_fee: 'Buy broker',
        sell_broker_fee: 'Sell broker',
        facility_tax: 'Facility tax',
        system_cost_index: 'System cost index',
        limit: 'Rows per page',
        hub_id: 'Product hub',
        material_hub_id: 'Material purchase hub'
      };
      return labels[field] || String(field).replaceAll('_', ' ').replace(/^./, v => v.toUpperCase());
    },
    async requestApi(url, options = {}) {
      const response = await fetch(url, {
        credentials: 'same-origin',
        ...options,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          ...options.headers
        }
      });
      let data;
      try {
        data = await window.readApiResponse(response);
      } catch (_) {
        data = null;
      }
      if (!response.ok) {
        if (response.status === 422 && Array.isArray(data?.detail)) throw new Error(data.detail.map(e => this.fieldLabel(e.loc.at(-1)) + ': ' + e.msg.replace(/^Value error, /, '')).join(' · '));
        if (response.status === 401) {
          location.assign('/login');
          throw new Error('Your session expired. Please log in again.');
        }
        throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not load data from the service. Please try again.');
      }
      return data;
    },
    params(form = this.form, settings = this.profileSettings, offset = this.page.offset) {
      const params = new URLSearchParams();
      const values = {
        ...this.migrateBrokerSettings({
          ...settings
        }),
        ...form
      };
      delete values.invention_science_level;
      delete values.invention_encryption_level;
      delete values.tech;
      delete values.category;
      delete values.rigs;
      delete values.meta_group_ids;
      delete values.categories;
      delete values.is_rig;
      if (form.tech === '__profile__') values.meta_group_ids = settings.meta_group_ids;
      else if (form.tech) values.meta_group_ids = [Number(form.tech)];
      if (form.category === '__profile__') {
        values.categories = settings.categories;
        values.is_rig = settings.is_rig;
      } else if (form.category === 'Rigs') values.is_rig = true;
      else if (form.category === 'Modules') {
        values.categories = ['Ship Equipment'];
        values.is_rig = false;
      } else if (form.category) values.categories = [form.category];
      if (this.calculator) {
        const allowed = ['manufacturing_runs', 'hub_id', 'material_hub_id', 'material_order_type', 'product_order_type', 'sales_tax', 'buy_broker_fee', 'sell_broker_fee', 'facility_tax', 'system_cost_index', 'include_invention_cost', 'buy_demand_tolerance_pct'];
        for (const key of Object.keys(values))
          if (!allowed.includes(key)) delete values[key];
      }
      if (!this.calculator) delete values.manufacturing_runs;
      if (!this.calculator) values.exclude_type_ids = [...new Set([...(values.exclude_type_ids || []), ...this.excludedItems.map(v => v.type_id)])];
      values.offset = offset;
      for (const [key, value] of Object.entries(values)) {
        if (value === null || value === undefined || value === '') continue;
        if (Array.isArray(value)) value.forEach(v => params.append(key, String(v)));
        else params.set(key, String(value));
      }
      return params;
    },
    async resetFilters() {
      this.profileId = '';
      this.profileSettings = {};
      this.form = this.getDefaultSettings();
      await this.load(false, 0);
    },
    get resultForm() {
      return this.appliedForm || this.form;
    },
    get hasChanges() {
      return this.appliedForm !== null && (JSON.stringify(this.form) !== JSON.stringify(this.appliedForm) || JSON.stringify(this.profileSettings) !== JSON.stringify(this.appliedSettings) || (this.calculator && Number(this.blueprint.type_id) !== this.appliedBlueprintId));
    },
    async load(useApplied = false, offset = this.page.offset) {
      if (this.calculator && !this.blueprint.type_id) {
        this.error = 'Choose a blueprint from the suggestions.';
        return;
      }
      const typeId = this.calculator ? Number(useApplied && this.appliedBlueprintId ? this.appliedBlueprintId : this.blueprint.type_id) : 0;
      this.saveSettings();
      const queryForm = JSON.parse(JSON.stringify(useApplied && this.appliedForm ? this.appliedForm : this.form));
      const querySettings = JSON.parse(JSON.stringify(useApplied && this.appliedForm ? this.appliedSettings : this.profileSettings));
      const seq = ++this.requestSequence;
      this.loading = true;
      this.error = '';
      try {
        let result;
        if (this.demo) result = this.demoPage(queryForm, offset);
        else result = await this.requestApi((this.calculator ? '/api/v1/manufacturing/calculator/' + typeId : '/api/v1/manufacturing/opportunities') + '?' + this.params(queryForm, querySettings, offset));
        if (seq !== this.requestSequence) return;
        this.closeItem();
        this.page = result;
        this.appliedForm = queryForm;
        this.appliedSettings = querySettings;
        this.appliedBlueprintId = typeId;
        if (this.calculator) await this.loadMaterialNames();
        else this.loadProgress();
      } catch (error) {
        if (seq === this.requestSequence) {
          this.error = error.message;
        }
      } finally {
        if (seq === this.requestSequence) this.loading = false;
      }
    },
    nextPage() {
      this.load(true, this.page.offset + this.page.limit);
    },
    previousPage() {
      this.load(true, Math.max(0, this.page.offset - this.page.limit));
    },
    get missingCount() {
      return (this.page.missing_recipes || 0) + (this.page.missing_prices || 0) + (this.page.missing_invention || 0) + (this.page.missing_job_costs || 0);
    },
    get topDaily() {
      return this.page.items.length ? Math.max(...this.page.items.map(p => Number(p.rank_profit_per_day))) : null;
    },
    get medianMargin() {
      const values = this.page.items.map(p => Number(p.margin_pct)).sort((a, b) => a - b);
      if (!values.length) return null;
      const i = Math.floor(values.length / 2);
      return values.length % 2 ? values[i] : (values[i - 1] + values[i]) / 2;
    },
    get activeFilters() {
      return ['search', 'tech', 'category', 'min_profit', 'min_margin', 'max_price_increase_pct', 'max_daily_volume_share_pct', 'min_daily_isk_volume', 'min_product_volume'].filter(k => this.form[k] !== '' && this.form[k] !== undefined).length + Number(this.form.include_invention_cost) + Number(this.form.fresh_only) + Number(this.form.require_full_run_demand);
    },
    get rangeLabel() {
      return this.page.total ? `${this.page.offset+1}–${Math.min(this.page.offset+this.page.limit,this.page.total)} of ${this.page.total.toLocaleString('en-US')} opportunities` : 'No matching opportunities';
    },
    getHubName(id) {
      return this.hubs.find(h => h.id === id)?.name || id;
    },
    formatMoney(value) {
      if (value === null || value === undefined) return '—';
      const n = Number(value);
      if (!Number.isFinite(n)) return '—';
      return new Intl.NumberFormat('en-US', {
        notation: Math.abs(n) >= 1000000 ? 'compact' : 'standard',
        maximumFractionDigits: Math.abs(n) >= 1000000 || Math.abs(n) < 100 ? 2 : 0
      }).format(n);
    },
    formatPercent(value) {
      return Number.isFinite(Number(value)) ? Number(value).toFixed(1) + '%' : '—';
    },
    formatFullMoney(value) {
      if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'Not available';
      return new Intl.NumberFormat('en-US', {
        maximumFractionDigits: 2
      }).format(Number(value));
    },
    demandTolerance() {
      const value = this.resultForm.buy_demand_tolerance_pct;
      return value === undefined || value === null || value === '' ? 5 : Number(value);
    },
    demandWarning(code) {
      return {
        single_buy_order: 'Only one buy order is available. Its removal could eliminate this selling opportunity.',
        single_buy_order_at_best: 'Only one order offers the best buy price. The displayed profit may disappear when it fills.',
        buy_order_count_unknown: 'The number of buy orders is unknown. Check available demand before building.',
        insufficient_buy_volume_for_one_run: 'Buy orders within your selected price range cannot absorb one full production run.'
      } [code] || 'Check the available buy demand before building.';
    },
    getProductionLineCount() {
      return Number(this.resultForm.production_lines) || 1;
    },
    getDailyVolumeShareColor(value) {
      if (value == null || !Number.isFinite(Number(value))) return '';
      const share = Number(value);
      const hue = share <= 10 ? 120 : share <= 15 ? 60 : share <= 20 ? 30 : 0;
      return 'hsl(' + hue + ', 70%, 65%)';
    },
    getPriceChangeColor(value) {
      if (value == null) return '';
      const progress = Math.max(0, Math.min(1, (Number(value) - 10) / 40));
      return 'hsl(' + (120 * (1 - progress)) + ', 70%, 65%)';
    },
    formatBpcDuration(seconds) {
      if (seconds == null || !Number.isFinite(Number(seconds)) || Number(seconds) <= 0) return 'N/A';
      const minutes = Math.ceil(Number(seconds) / 60);
      return Math.floor(minutes / 60) + 'h ' + (minutes % 60) + 'm';
    },
    getBpcDurationColor(seconds) {
      if (seconds == null || !Number.isFinite(Number(seconds)) || Number(seconds) <= 0) return '';
      const minimumSeconds = 30 * 60;
      const yellowSeconds = 6 * 60 * 60;
      const maximumSeconds = 24 * 60 * 60;
      const durationSeconds = Math.max(minimumSeconds, Math.min(maximumSeconds, Number(seconds)));
      const hue = durationSeconds <= yellowSeconds
        ? 60 * (durationSeconds - minimumSeconds) / (yellowSeconds - minimumSeconds)
        : 60 + 60 * (durationSeconds - yellowSeconds) / (maximumSeconds - yellowSeconds);
      return 'hsl(' + hue + ', 70%, 65%)';
    },
    formatDemandDuration(item) {
      if (item.demand_duration_seconds !== null && item.demand_duration_seconds !== undefined) return this.duration(item.demand_duration_seconds);
      const runs = item.full_runs_at_buy_price,
        seconds = Number(item.seconds);
      if (runs === null || runs === undefined || !Number.isFinite(seconds) || seconds <= 0) return 'Not available';
      return this.duration(seconds * Math.ceil(runs / this.getProductionLineCount()));
    },
    duration(seconds) {
      const n = Number(seconds);
      if (!Number.isFinite(n) || n < 0) return 'Not available';
      const total = Math.ceil(n),
        d = Math.floor(total / 86400),
        h = Math.floor(total % 86400 / 3600),
        m = Math.floor(total % 3600 / 60),
        s = total % 60;
      return d ? (d + 'd ' + h + 'h ' + m + 'm') : h ? (h + 'h ' + m + 'm') : m ? (m + 'm ' + s + 's') : s + 's';
    },
    demoPage(form = this.form, offset = this.page.offset) {
      const seeds = [
        ['Damage Control II', 2048, 2, 137000, 91000, 66.4, 9200000, 890000000],
        ['Hobgoblin II', 2456, 2, 173000, 62000, 35.8, 6800000, 1540000000],
        ['Medium Core Defense Field Extender II', 31796, 2, 820000, 244000, 29.7, 5300000, 612000000],
        ['Warrior II', 2488, 2, 206000, 73000, 35.4, 4100000, 940000000],
        ['Scourge Heavy Missile', 209, 1, 48, 17, 35.4, 3600000, 2640000000],
        ['Gyrostabilizer II', 519, 2, 610000, 128000, 20.9, 2900000, 731000000],
        ['Large Shield Extender II', 3841, 2, 936000, 164000, 17.5, 2100000, 483000000]
      ];
      let items = seeds.map((s, i) => ({
        _category: i === 2 ? 'Rigs' : [1, 3].includes(i) ? 'Drones' : i === 4 ? 'Ammunition & Charges' : 'Modules',
        name: s[0],
        type_id: s[1],
        meta_group_id: s[2],
        total_cost_per_unit: String(s[3]),
        material_cost_per_unit: String(s[3] * 0.96),
        job_cost_per_unit: String(s[3] * 0.04),
        profit_per_unit: String(s[4]),
        margin_pct: String(s[5]),
        rank_profit_per_day: String(s[6]),
        profit_per_day: String(s[6] * 1.2),
        daily_isk_volume: String(s[7]),
        units: 1,
        seconds: '7200',
        revenue_per_unit: String(s[3] + s[4]),
        historical_median_price: String((s[3] + s[4]) / 1.2),
        price_change_pct: '20',
        invention_required: s[2] === 2,
        invention_included: false,
        invention_cost_per_unit: '0',
        sales_tax_per_unit: '0',
        sales_broker_fee_per_unit: '0',
        procurement_broker_fee_per_unit: '0',
        stale: i === 5,
        demand_warnings: i === 4 ? ['single_buy_order_at_best'] : [],
        product_volume_at_price: 100,
        full_runs_at_buy_price: 100,
        production_limit_units: 100,
        profit_at_current_buy_price: String(s[4] * 100),
        materials: [{
          type_id: 34,
          quantity: 100,
          price: String(s[3] * 0.96 / 100),
          cost: String(s[3] * 0.96)
        }]
      }));
      if (form.product_order_type !== 'buy') items.forEach(i => {
        i.profit_at_current_buy_price = null;
        i.production_limit_units = null;
        i.full_runs_at_buy_price = null;
      });
      items = items.filter(i => (form.max_daily_volume_share_pct === '' || (i.daily_volume_share_pct != null && Number(i.daily_volume_share_pct) <= Number(form.max_daily_volume_share_pct))) && (form.max_price_increase_pct === '' || Number(i.price_change_pct) <= Number(form.max_price_increase_pct)) && (!form.category || form.category === '__profile__' || i._category === form.category) && (!form.min_daily_isk_volume || Number(i.daily_isk_volume) >= Number(form.min_daily_isk_volume)) && (!form.min_product_volume || i.product_volume_at_price >= Number(form.min_product_volume)) && (!form.search || i.name.toLowerCase().includes(form.search.toLowerCase())) && (!form.tech || i.meta_group_id === Number(form.tech)) && (!form.min_profit || Number(i.profit_per_unit) >= Number(form.min_profit)) && (!form.min_margin || Number(i.margin_pct) >= Number(form.min_margin)) && (!form.fresh_only || !i.stale));
      if (!this.calculator) items = items.filter(item => !this.excludedItems.some(v => v.type_id === item.type_id));
      if (this.calculator) items = items.filter(item => item.type_id === Number(this.blueprint.type_id));
      const rank = {
        profit_per_day: 'rank_profit_per_day',
        margin: 'margin_pct',
        profit: 'profit_per_unit',
        demand_profit: 'profit_at_current_buy_price'
      } [form.rank_by];
      items.sort((a, b) => (a[rank] === null) - (b[rank] === null) || Number(b[rank]) - Number(a[rank]) || a.type_id - b.type_id);
      return {
        items: items.slice(offset, offset + Number(form.limit)),
        total: items.length,
        offset: offset,
        limit: Number(form.limit)
      };
    }
  }));
});

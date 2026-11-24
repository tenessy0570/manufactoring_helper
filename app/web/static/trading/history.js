window.tradingHistory = () => ({
  ...window.marketHistoryChartMethods,
  historyItem: null,
  historyData: null,
  historyLoading: false,
  historyError: '',
  historyHoverText: '',
  historyPeriod: 30,
  historySaleSide: 'buy',
  historySequence: 0,
  historyReturnFocus: null,
  historyOverflow: '',
  async openHistory(item) {
    if (!this.historyItem) {
      this.historyReturnFocus = document.activeElement;
      this.historyOverflow = document.body.style.overflow;
    }
    this.historyItem = {
      ...item
    };
    this.historyPeriod = Number(this.resultForm.history_days) || 30;
    this.historySaleSide = this.resultForm.sale_side;
    this.historyData = null;
    this.historyError = '';
    this.historyHoverText = '';
    await this.$nextTick();
    if (!this.$refs.historyDialog.open) this.$refs.historyDialog.showModal();
    document.body.style.overflow = 'hidden';
    this.$refs.historyClose.focus();
    await this.loadHistory();
  },
  closeHistory() {
    this.historySequence++;
    if (this.$refs.historyDialog.open) this.$refs.historyDialog.close();
    this.historyItem = null;
    this.historyLoading = false;
    this.historyData = null;
    document.body.style.overflow = this.historyOverflow;
    if (this.historyReturnFocus?.isConnected) this.historyReturnFocus.focus();
  },
  historyOutside(event) {
    if (event.target !== this.$refs.historyDialog) return;
    const r = event.target.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) this.closeHistory();
  },
  async loadHistory() {
    if (!this.historyItem) return;
    const seq = ++this.historySequence,
      item = this.historyItem;
    this.historyLoading = true;
    this.historyError = '';
    this.historyData = null;
    this.historyHoverText = '';
    try {
      const params = new URLSearchParams({
        hub_id: item.destination_hub,
        days: String(this.historyPeriod)
      });
      const response = await fetch('/api/v1/market/history/' + item.type_id + '?' + params, {
        credentials: 'same-origin'
      });
      if (response.status === 401) {
        location.assign('/login');
        throw Error('Session expired.');
      }
      if (!response.ok) throw Error('Saved trading history could not be loaded.');
      const data = await window.readApiResponse(response);
      if (seq !== this.historySequence) return;
      this.historyData = {
        ...data,
        days: [...data.days].sort((a, b) => a.date.localeCompare(b.date))
      };
    } catch (error) {
      if (seq === this.historySequence) this.historyError = error.message;
    } finally {
      if (seq === this.historySequence) this.historyLoading = false;
    }
  },
});

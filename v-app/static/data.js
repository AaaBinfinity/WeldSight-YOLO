(() => {
  const pageSize =  7;
  let offset = 0;
  let total = 0;
  let currentItems = [];
  const selected = new Set();
  let toastTimer = 0;

  const labels = {
    image: '图片检测',
    batch: '批量检测',
    camera: '实时检测',
    completed: '已完成',
    queued: '排队中',
    processing: '复核中',
    failed: '失败',
    not_configured: '未配置',
    disabled: '已关闭',
    accepted: '结果接受',
    confirmed: '确认缺陷',
    false_positive: '确认误报',
    missed_defect: '确认漏报',
    mixed: '混合结论',
    pending: '待复核'
  };

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    })[character]);
  }

  function formatNumber(value) {
    return new Intl.NumberFormat('zh-CN').format(Number(value || 0));
  }

  function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (value < 1024) return `${value} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let number = value / 1024;
    let index = 0;
    while (number >= 1024 && index < units.length - 1) {
      number /= 1024;
      index += 1;
    }
    return `${number >= 100 ? number.toFixed(0) : number.toFixed(1)} ${units[index]}`;
  }

  function localTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? value
      : date.toLocaleString('zh-CN', { hour12: false });
  }

  function badge(value, fallback = '待复核') {
    const normalized = value || 'pending';
    const tone = ['completed', 'accepted', 'confirmed'].includes(normalized)
      ? 'success'
      : ['queued', 'processing'].includes(normalized)
        ? 'working'
        : ['failed', 'false_positive', 'missed_defect'].includes(normalized)
          ? 'error'
          : '';
    return `<span class="status-badge ${tone}">${escapeHtml(labels[normalized] || fallback || normalized)}</span>`;
  }

  function showToast(message, type = 'success') {
    const toast = document.getElementById('dataToast');
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.className = `data-toast show${type === 'error' ? ' error' : ''}`;
    toastTimer = setTimeout(() => {
      toast.className = 'data-toast';
    }, 4200);
  }

  function openDialog(id) {
    const dialog = document.getElementById(id);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  }

  function closeDialog(id) {
    const dialog = document.getElementById(id);
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }

  function selectedIdsQuery() {
    return [...selected].map(id => `id=${encodeURIComponent(id)}`).join('&');
  }

  function download(url) {
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = '';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  function updateSelectionUi() {
    document.getElementById('selectedCount').textContent = selected.size;
    document.getElementById('exportSelectedButton').disabled = selected.size === 0;
    document.getElementById('deleteSelectedButton').disabled = selected.size === 0;
    const currentIds = currentItems.map(item => item.id);
    const selectedOnPage = currentIds.filter(id => selected.has(id)).length;
    const selectPage = document.getElementById('selectPage');
    selectPage.checked = currentIds.length > 0 && selectedOnPage === currentIds.length;
    selectPage.indeterminate = selectedOnPage > 0 && selectedOnPage < currentIds.length;
    document.querySelectorAll('[data-record-check]').forEach(checkbox => {
      checkbox.checked = selected.has(checkbox.dataset.recordCheck);
    });
  }

  async function loadOverview() {
    try {
      const response = await fetch('/api/data/overview');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '读取数据概览失败');
      const database = data.database;
      const storage = data.storage;
      const reviewRate = database.total_records
        ? database.reviewed_records / database.total_records * 100
        : 0;
      document.getElementById('metricRecords').textContent = formatNumber(database.total_records);
      document.getElementById('metricRecordsDetail').textContent =
        `${formatNumber(database.total_batches)} 个批次 · ${formatNumber(database.total_detections)} 个候选缺陷`;
      document.getElementById('metricReviewed').textContent = formatNumber(database.reviewed_records);
      document.getElementById('metricReviewedDetail').textContent = `复核完成率 ${reviewRate.toFixed(1)}%`;
      document.getElementById('metricFiles').textContent = formatNumber(storage.total_files);
      document.getElementById('metricFilesDetail').textContent =
        `${formatNumber(storage.feedback_entries)} 条人工反馈样本`;
      document.getElementById('metricStorage').textContent = formatBytes(storage.total_bytes);
      document.getElementById('databaseHost').textContent = `${database.host}:${database.port}`;
      document.getElementById('databaseName').textContent = database.name;
      document.getElementById('databaseState').textContent = database.connected ? '已连接' : '不可用';
      document.getElementById('recordFiles').textContent =
        `${formatNumber(storage.records.files)} 个 · ${formatBytes(storage.records.bytes)}`;
      document.getElementById('batchFiles').textContent =
        `${formatNumber(storage.batches.files)} 个 · ${formatBytes(storage.batches.bytes)}`;
      document.getElementById('uploadFiles').textContent =
        `${formatNumber(storage.uploads.files)} 个 · ${formatBytes(storage.uploads.bytes)}`;
      document.getElementById('feedbackEntries').textContent =
        `${formatNumber(storage.feedback_entries)} 条 · ${formatBytes(storage.feedback_bytes)}`;
      const ratio = storage.total_bytes
        ? storage.records.bytes / storage.total_bytes * 100
        : 0;
      document.getElementById('storageFill').style.width = `${Math.max(0, Math.min(ratio, 100))}%`;
      document.getElementById('storageRatio').textContent = `${ratio.toFixed(1)}%`;
    } catch (error) {
      document.getElementById('databaseState').textContent = '读取失败';
      showToast(error.message, 'error');
    }
  }

  async function loadRecords() {
    const params = new URLSearchParams({
      limit: pageSize,
      offset,
      q: document.getElementById('searchInput').value.trim(),
      source_type: document.getElementById('sourceFilter').value,
      ai_status: document.getElementById('aiFilter').value
    });
    const rows = document.getElementById('dataRows');
    rows.innerHTML = '<tr><td class="table-empty" colspan="8">正在读取检测数据…</td></tr>';
    try {
      const response = await fetch(`/api/inspections?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '读取检测数据失败');
      currentItems = data.items;
      total = data.total;
      document.getElementById('tableTotal').textContent = `${formatNumber(total)} 条记录`;
      document.getElementById('pageSummary').textContent = total
        ? `第 ${Math.floor(offset / pageSize) + 1} 页 · 共 ${formatNumber(total)} 条`
        : '暂无记录';
      document.getElementById('previousPage').disabled = offset === 0;
      document.getElementById('nextPage').disabled = offset + pageSize >= total;
      if (!currentItems.length) {
        rows.innerHTML = '<tr><td class="table-empty" colspan="8">没有符合筛选条件的检测记录。</td></tr>';
        updateSelectionUi();
        return;
      }
      rows.innerHTML = currentItems.map(record => {
        const classNames = Object.keys(record.class_counts || {}).join('、') || '未检出';
        return `
          <tr>
            <td data-label="选择"><input class="data-checkbox" data-record-check="${record.id}" type="checkbox" aria-label="选择 ${escapeHtml(record.source_name)}"></td>
            <td data-label="检测编号 / 文件名">
              <strong class="data-record-name">${escapeHtml(record.source_name)}</strong>
              <span class="table-sub data-record-id">#${escapeHtml(record.id.slice(0, 10).toUpperCase())}</span>
            </td>
            <td data-label="来源"><span class="source-label">${escapeHtml(labels[record.source_type] || record.source_type)}</span></td>
            <td data-label="缺陷"><strong>${formatNumber(record.detection_count)}</strong><span class="table-sub">${escapeHtml(classNames)}</span></td>
            <td data-label="AI 状态">${badge(record.ai_status, record.ai_status)}</td>
            <td data-label="人工复核">${badge(record.review_decision, '待复核')}</td>
            <td data-label="检测时间">${escapeHtml(localTime(record.created_at))}</td>
            <td data-label="操作"><div class="table-actions">
              <a class="icon-button" href="/history.html?record=${encodeURIComponent(record.id)}">详情</a>
              <a class="icon-button" href="${record.pdf_url}" target="_blank">PDF</a>
            </div></td>
          </tr>
        `;
      }).join('');
      rows.querySelectorAll('[data-record-check]').forEach(checkbox => {
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) selected.add(checkbox.dataset.recordCheck);
          else selected.delete(checkbox.dataset.recordCheck);
          updateSelectionUi();
        });
      });
      updateSelectionUi();
    } catch (error) {
      rows.innerHTML = `<tr><td class="table-empty" colspan="8">${escapeHtml(error.message)}</td></tr>`;
      showToast(error.message, 'error');
    }
  }

  async function postJson(url, payload, method = 'POST') {
    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '操作失败');
    return data;
  }

  document.getElementById('selectPage').addEventListener('change', event => {
    currentItems.forEach(record => {
      if (event.target.checked) selected.add(record.id);
      else selected.delete(record.id);
    });
    updateSelectionUi();
  });

  let searchTimer;
  ['searchInput', 'sourceFilter', 'aiFilter'].forEach(id => {
    document.getElementById(id).addEventListener(id === 'searchInput' ? 'input' : 'change', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        offset = 0;
        loadRecords();
      }, 240);
    });
  });

  document.getElementById('refreshButton').addEventListener('click', () => {
    loadOverview();
    loadRecords();
  });
  document.getElementById('previousPage').addEventListener('click', () => {
    offset = Math.max(0, offset - pageSize);
    loadRecords();
  });
  document.getElementById('nextPage').addEventListener('click', () => {
    if (offset + pageSize < total) {
      offset += pageSize;
      loadRecords();
    }
  });
  document.getElementById('exportSelectedButton').addEventListener('click', () => {
    download(`/api/data/export.zip?${selectedIdsQuery()}&include_files=1`);
  });
  document.getElementById('deleteSelectedButton').addEventListener('click', () => {
    document.getElementById('deleteDialogCount').textContent = selected.size;
    openDialog('deleteDialog');
  });
  document.getElementById('exportAllJson').addEventListener('click', () => {
    download('/api/data/export.json');
  });
  document.getElementById('exportAllZip').addEventListener('click', () => {
    download('/api/data/export.zip?include_files=1');
  });
  document.getElementById('cleanupButton').addEventListener('click', () => {
    openDialog('cleanupDialog');
  });
  document.getElementById('purgeButton').addEventListener('click', () => {
    document.getElementById('purgeConfirmation').value = '';
    document.getElementById('confirmPurgeButton').disabled = true;
    openDialog('purgeDialog');
  });
  document.querySelectorAll('[data-close-dialog]').forEach(button => {
    button.addEventListener('click', () => closeDialog(button.dataset.closeDialog));
  });

  document.getElementById('confirmDeleteButton').addEventListener('click', async event => {
    event.target.disabled = true;
    try {
      const data = await postJson('/api/data/records', { ids: [...selected] }, 'DELETE');
      closeDialog('deleteDialog');
      showToast(`已删除 ${data.deleted_records} 条记录，释放 ${formatBytes(data.reclaimed_bytes)}。`);
      selected.clear();
      if (offset >= Math.max(0, total - data.deleted_records)) {
        offset = Math.max(0, offset - pageSize);
      }
      await Promise.all([loadOverview(), loadRecords()]);
    } catch (error) {
      showToast(error.message, 'error');
    } finally {
      event.target.disabled = false;
    }
  });

  document.getElementById('confirmCleanupButton').addEventListener('click', async event => {
    event.target.disabled = true;
    try {
      const data = await postJson('/api/data/cleanup', { confirmation: 'CLEAN ORPHANS' });
      closeDialog('cleanupDialog');
      showToast(`已清理 ${data.removed_directories} 个孤立目录，释放 ${formatBytes(data.reclaimed_bytes)}。`);
      await loadOverview();
    } catch (error) {
      showToast(error.message, 'error');
    } finally {
      event.target.disabled = false;
    }
  });

  document.getElementById('purgeConfirmation').addEventListener('input', event => {
    document.getElementById('confirmPurgeButton').disabled =
      event.target.value.trim() !== '清空检测数据';
  });
  document.getElementById('confirmPurgeButton').addEventListener('click', async event => {
    event.target.disabled = true;
    try {
      const data = await postJson('/api/data/purge', { confirmation: 'CLEAR WELDSIGHT DATA' });
      closeDialog('purgeDialog');
      showToast(`已清空 ${data.deleted_records} 条记录和 ${data.deleted_batches} 个批次，系统设置已保留。`);
      selected.clear();
      offset = 0;
      await Promise.all([loadOverview(), loadRecords()]);
    } catch (error) {
      showToast(error.message, 'error');
      event.target.disabled = false;
    }
  });

  Promise.all([loadOverview(), loadRecords()]);
})();

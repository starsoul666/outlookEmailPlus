// ===== Pool Admin Feature Module (Issue #60) =====

let __poolAdminState = {
    page: 1,
    pageSize: 20,
    loading: false,
    cache: null,
    groupOptionsLoaded: false,
};

function paT(text) {
    if (text === null || text === undefined || text === '') return '';
    if (typeof translateAppTextLocal === 'function') return translateAppTextLocal(text);
    if (window.translateAppText) return window.translateAppText(text);
    return String(text);
}

function loadPoolAdmin(forceRefresh = false) {
    const wrapper = document.getElementById('poolAdminTableWrapper');
    if (!wrapper) return;

    ensurePoolAdminGroupOptions();

    if (!forceRefresh && __poolAdminState.cache) {
        renderPoolAdmin(__poolAdminState.cache);
        return;
    }

    const inPool = document.getElementById('poolAdminInPoolFilter')?.value || 'all';
    const poolStatus = document.getElementById('poolAdminStatusFilter')?.value || '';
    const provider = document.getElementById('poolAdminProviderFilter')?.value || '';
    const groupId = document.getElementById('poolAdminGroupFilter')?.value || '';
    const search = document.getElementById('poolAdminSearch')?.value || '';

    __poolAdminState.loading = true;
    wrapper.innerHTML = '<div class="loading-overlay"><span class="spinner"></span> ' + paT('加载中…') + '</div>';

    const params = new URLSearchParams();
    params.set('in_pool', inPool);
    if (poolStatus) params.set('pool_status', poolStatus);
    if (provider) params.set('provider', provider);
    if (groupId) params.set('group_id', groupId);
    if (search) params.set('search', search);
    params.set('page', String(__poolAdminState.page));
    params.set('page_size', String(__poolAdminState.pageSize));

    fetch('/api/pool-admin/accounts?' + params.toString())
        .then(r => r.json())
        .then(data => {
            __poolAdminState.cache = data;
            renderPoolAdmin(data);
        })
        .catch(err => {
            wrapper.innerHTML = '<div class="ov-empty" style="padding:2rem;">' + paT('加载失败') + ': ' + String(err) + '</div>';
        })
        .finally(() => {
            __poolAdminState.loading = false;
        });
}

function ensurePoolAdminGroupOptions(forceRefresh = false) {
    const select = document.getElementById('poolAdminGroupFilter');
    if (!select) return;
    if (!forceRefresh && __poolAdminState.groupOptionsLoaded) return;

    const selectedValue = select.value || '';

    fetch('/api/groups')
        .then(r => r.json())
        .then(data => {
            const groups = Array.isArray(data?.groups) ? data.groups : [];
            const optionsHtml = ['<option value="">' + paT('所有分组') + '</option>'];
            groups.forEach(group => {
                const id = String(group.id ?? '').trim();
                if (!id) return;
                const name = escapeHtml(group.name || id);
                optionsHtml.push(`<option value="${id}">${name}</option>`);
            });
            select.innerHTML = optionsHtml.join('');
            if (selectedValue && select.querySelector(`option[value="${selectedValue}"]`)) {
                select.value = selectedValue;
            }
            __poolAdminState.groupOptionsLoaded = true;
        })
        .catch(() => {
            // 分组加载失败不阻断列表查询
        });
}

let __poolAdminSearchDebounce = null;
function debouncePoolAdminSearch() {
    if (__poolAdminSearchDebounce) clearTimeout(__poolAdminSearchDebounce);
    __poolAdminSearchDebounce = setTimeout(() => {
        __poolAdminState.page = 1;
        loadPoolAdmin(true);
    }, 400);
}

function renderPoolAdmin(data) {
    const wrapper = document.getElementById('poolAdminTableWrapper');
    const paginationEl = document.getElementById('poolAdminPagination');
    if (!wrapper) return;

    const items = data.items || [];
    if (items.length === 0) {
        wrapper.innerHTML = '<div class="ov-empty" style="padding:2rem;">' + paT('暂无数据') + '</div>';
        if (paginationEl) paginationEl.innerHTML = '';
        return;
    }

    const statusLabelMap = {
        'available': { text: '可用', cls: 'status-badge status-success' },
        'claimed': { text: '占用中', cls: 'status-badge status-warning' },
        'cooldown': { text: '冷却中', cls: 'status-badge status-info' },
        'used': { text: '已使用', cls: 'status-badge status-muted' },
        'frozen': { text: '冻结', cls: 'status-badge status-danger' },
        'retired': { text: '退休', cls: 'status-badge status-muted' },
    };

    const rows = items.map(item => {
        const status = item.pool_status || 'NULL';
        const statusInfo = statusLabelMap[status] || { text: status || 'NULL', cls: 'status-badge' };
        const isClaimed = status === 'claimed';

        // 动作按钮
        let actionsHtml = '';
        if (isClaimed) {
            actionsHtml = `<button class="btn btn-sm btn-warning" onclick="confirmPoolAdminAction(${item.id}, 'force_release', '${item.email}')">${paT('强制释放')}</button>`;
        } else {
            if (status === 'NULL') {
                actionsHtml = `<button class="btn btn-sm btn-primary" onclick="confirmPoolAdminAction(${item.id}, 'move_into_pool', '${item.email}')">${paT('移入号池')}</button>`;
            } else {
                actionsHtml = `<button class="btn btn-sm btn-ghost" onclick="confirmPoolAdminAction(${item.id}, 'move_out_of_pool', '${item.email}')">${paT('移出号池')}</button>`;
                if (['cooldown', 'used', 'frozen', 'retired'].includes(status)) {
                    actionsHtml += ` <button class="btn btn-sm btn-primary" onclick="confirmPoolAdminAction(${item.id}, 'restore_available', '${item.email}')">${paT('恢复可用')}</button>`;
                }
                if (['available', 'cooldown', 'used'].includes(status)) {
                    actionsHtml += ` <button class="btn btn-sm btn-info" onclick="confirmPoolAdminAction(${item.id}, 'freeze', '${item.email}')">${paT('冻结')}</button>`;
                }
                if (['available', 'cooldown', 'used', 'frozen'].includes(status)) {
                    actionsHtml += ` <button class="btn btn-sm btn-danger" onclick="confirmPoolAdminAction(${item.id}, 'retire', '${item.email}')">${paT('退休')}</button>`;
                }
            }
        }

        const claimedInfo = isClaimed
            ? `<div style="font-size:0.8rem;color:var(--text-muted);">${paT('占用方')}: ${escapeHtml(item.claimed_by || '')} · ${escapeHtml(item.claimed_at || '').slice(0, 16)}</div>`
            : '';

        return `<tr>
            <td style="white-space:nowrap;">${escapeHtml(item.email)}</td>
            <td>${escapeHtml(item.group_name || '-')}</td>
            <td>${escapeHtml(item.provider || '-')}</td>
            <td><span class="${statusInfo.cls}">${paT(statusInfo.text)}</span></td>
            <td>${escapeHtml(item.last_result || '-')}</td>
            <td style="min-width:220px;">
                ${claimedInfo}
                <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;">${actionsHtml}</div>
            </td>
        </tr>`;
    }).join('');

    wrapper.innerHTML = `<div class="table-responsive">
        <table class="data-table">
            <thead>
                <tr>
                    <th>${paT('邮箱')}</th>
                    <th>${paT('分组')}</th>
                    <th>${paT('类型')}</th>
                    <th>${paT('池状态')}</th>
                    <th>${paT('最近结果')}</th>
                    <th>${paT('操作')}</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    </div>`;

    // 分页
    if (paginationEl) {
        const total = data.total || 0;
        const page = data.page || 1;
        const pageSize = data.page_size || 20;
        const totalPages = data.total_pages || 1;
        if (totalPages > 1) {
            let pagesHtml = '';
            for (let i = 1; i <= totalPages; i++) {
                const activeClass = i === page ? 'btn-primary' : 'btn-ghost';
                pagesHtml += `<button class="btn btn-sm ${activeClass}" onclick="goPoolAdminPage(${i})">${i}</button>`;
            }
            paginationEl.innerHTML = `<div style="display:flex;gap:6px;align-items:center;justify-content:center;">
                <span>${paT('共')} ${total} ${paT('条')} · ${paT('第')} ${page}/${totalPages} ${paT('页')}</span>
                ${pagesHtml}
            </div>`;
        } else {
            paginationEl.innerHTML = `<div style="text-align:center;color:var(--text-muted);">${paT('共')} ${total} ${paT('条')}</div>`;
        }
    }
}

function goPoolAdminPage(page) {
    __poolAdminState.page = page;
    loadPoolAdmin(true);
}

function confirmPoolAdminAction(accountId, action, email) {
    const actionNames = {
        'move_into_pool': '移入号池',
        'move_out_of_pool': '移出号池',
        'restore_available': '恢复可用',
        'freeze': '冻结',
        'retire': '退休',
        'force_release': '强制释放',
    };
    const actionName = actionNames[action] || action;
    const msg = `${paT('确定对')} ${escapeHtml(email)} ${paT('执行')}「${paT(actionName)}」${paT('吗？')}`;
    if (!confirm(msg)) return;

    fetch(`/api/pool-admin/accounts/${accountId}/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                showToast(paT('操作成功'), 'success');
                loadPoolAdmin(true);
            } else {
                showToast(data.message || paT('操作失败'), 'error');
            }
        })
        .catch(err => {
            showToast(paT('请求失败') + ': ' + String(err), 'error');
        });
}

function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

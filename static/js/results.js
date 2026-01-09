/**
 * Results display for the Site Parity Checker.
 */

import { getEl, setText, setHtml, show, hide } from './utils.js';

let currentData = {};
let activeTab = 'missing_on_new';

/**
 * Update results UI with comparison data.
 * @param {Object} data - Comparison result data
 */
export function updateResultsUI(data) {
    currentData = data;
    activeTab = 'missing_on_new';
    
    // Update counts
    setText('count-missing_on_new', data.missing_on_new.length);
    setText('count-new_only', data.new_only.length);
    setText('count-matched', data.matched.length);
    
    // Update summary totals
    const oldTotal = data.old_total || (data.missing_on_new.length + data.matched.length);
    const newTotal = data.new_total || (data.new_only.length + data.matched.length);
    
    setText('summaryOldTotal', oldTotal.toLocaleString());
    setText('summaryNewTotal', newTotal.toLocaleString());
    
    // Update breakdown section
    setText('breakdownOldTotal', oldTotal.toLocaleString());
    setText('breakdownNewTotal', newTotal.toLocaleString());
    setText('breakdownMatched', data.matched.length.toLocaleString());
    setText('breakdownMatched2', data.matched.length.toLocaleString());
    setText('breakdownMissing', data.missing_on_new.length.toLocaleString());
    setText('breakdownNewOnly', data.new_only.length.toLocaleString());
    
    // Update comparison notes
    updateComparisonNotes(oldTotal, newTotal);
    
    // Show warnings if present
    if (data.warnings && data.warnings.length > 0) {
        setText('warningTitle', data.warning_message || 'Some operations failed:');
        setHtml('warningList', data.warnings.map(w => `<li>${w}</li>`).join(''));
        show('warning');
    }
    
    // Show results
    hide('loading');
    show('results');
    
    // Show initial tab
    showTab('missing_on_new');
}

/**
 * Update comparison notes based on totals.
 * @param {number} oldTotal - Old site total
 * @param {number} newTotal - New site total
 */
function updateComparisonNotes(oldTotal, newTotal) {
    const diff = oldTotal - newTotal;
    const diffPercent = oldTotal > 0 ? ((Math.abs(diff) / oldTotal) * 100).toFixed(1) : 0;
    
    if (diff > 0) {
        setText('summaryOldNote', `+${diff.toLocaleString()} more pages`);
        setText('summaryNewNote', `${diffPercent}% fewer pages`);
        setHtml('summaryComparisonText', 
            `⚠️ <strong>Summary:</strong> The new site has ${diff.toLocaleString()} fewer pages than the old site. ` +
            `Check the "Missing on New" tab to see which pages need to be migrated.`
        );
        show('summaryComparisonNote');
    } else if (diff < 0) {
        const absDiff = Math.abs(diff);
        const newDiffPercent = newTotal > 0 ? ((absDiff / newTotal) * 100).toFixed(1) : 0;
        setText('summaryOldNote', `${newDiffPercent}% fewer pages`);
        setText('summaryNewNote', `+${absDiff.toLocaleString()} more pages`);
        setHtml('summaryComparisonText',
            `ℹ️ <strong>Summary:</strong> The new site has ${absDiff.toLocaleString()} more pages than the old site. ` +
            `These are new pages created after the migration. Check the "New Only" tab to see them.`
        );
        show('summaryComparisonNote');
    } else {
        setText('summaryOldNote', 'Same number of pages');
        setText('summaryNewNote', 'Same number of pages');
        hide('summaryComparisonNote');
    }
}

/**
 * Show a specific tab.
 * @param {string} tabName - Tab name to show
 */
export function showTab(tabName) {
    activeTab = tabName;
    
    // Update tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        if (btn.dataset.tab === tabName) {
            btn.classList.add('border-blue-500', 'text-blue-600');
            btn.classList.remove('text-gray-500', 'border-transparent');
        } else {
            btn.classList.remove('border-blue-500', 'text-blue-600');
            btn.classList.add('text-gray-500', 'border-transparent');
        }
    });
    
    // Update table
    const urls = currentData[tabName] || [];
    const tbody = getEl('tableBody');
    const empty = getEl('emptyMessage');
    const tableWrapper = tbody?.parentElement?.parentElement;
    
    if (urls.length === 0) {
        if (tbody) tbody.innerHTML = '';
        if (empty) empty.classList.remove('hidden');
        if (tableWrapper) tableWrapper.classList.add('hidden');
    } else {
        if (empty) empty.classList.add('hidden');
        if (tableWrapper) tableWrapper.classList.remove('hidden');
        
        if (tbody) {
            tbody.innerHTML = urls.map(url => {
                const path = new URL(url).pathname;
                return `
                    <tr class="hover:bg-gray-50">
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            <a href="${url}" target="_blank" class="text-blue-600 hover:text-blue-800">${url}</a>
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${path}</td>
                    </tr>
                `;
            }).join('');
        }
    }
}

/**
 * Get the current active tab name.
 * @returns {string} Active tab name
 */
export function getActiveTab() {
    return activeTab;
}

/**
 * Get the current comparison data.
 * @returns {Object} Current data
 */
export function getCurrentData() {
    return currentData;
}

/**
 * Initialize tab click handlers.
 */
export function initTabs() {
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.addEventListener('click', () => {
            showTab(btn.dataset.tab);
        });
    });
}


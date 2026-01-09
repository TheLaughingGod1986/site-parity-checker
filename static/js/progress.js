/**
 * Progress tracking and display for the Site Parity Checker.
 */

import { formatTime, formatETA, getEl, setText, setHtml, show, hide, setWidth } from './utils.js';

const DEFAULT_MAX_PAGES = 10000;

/**
 * Update the progress UI with data from the backend.
 * @param {Object} data - Progress data from backend
 */
export function updateProgressUI(data) {
    if (!data) return;
    
    // Update main progress bar
    const percentage = data.percentage || 0;
    setWidth('progressBarFill', `${percentage}%`);
    setText('progressPercentage', `${percentage.toFixed(1)}%`);
    
    // Get page counts
    const oldPages = data.old_site?.pages_scanned || 0;
    const newPages = data.new_site?.pages_scanned || 0;
    const totalPages = oldPages + newPages;
    
    const oldEstimate = data.old_site?.total_estimate > 0 ? data.old_site.total_estimate : DEFAULT_MAX_PAGES;
    const newEstimate = data.new_site?.total_estimate > 0 ? data.new_site.total_estimate : DEFAULT_MAX_PAGES;
    const totalEstimate = Math.max(oldEstimate, newEstimate, totalPages);
    
    // Update page counts
    setText('progressPages', `${totalPages} / ${totalEstimate}`);
    setText('statsOldPages', oldPages);
    setText('statsNewPages', newPages);
    
    // Calculate percentages
    const oldPercent = oldEstimate > 0 ? (oldPages / oldEstimate * 100) : 0;
    const newPercent = newEstimate > 0 ? (newPages / newEstimate * 100) : 0;
    
    // Update old site scan status
    updateSiteStatus('old', oldPages, oldEstimate, oldPercent);
    
    // Update new site scan status
    updateSiteStatus('new', newPages, newEstimate, newPercent);
    
    // Update comparison warning
    updateComparisonWarning(oldPercent, newPercent, newPages);
    
    // Update time - always update if we have data
    const elapsed = data.time?.elapsed_seconds ?? 0;
    setText('statsElapsedTime', formatTime(elapsed));
    
    // Update ETA
    const eta = data.time?.eta_seconds;
    if (eta !== null && eta !== undefined) {
        setText('statsETA', formatETA(eta));
    }
    
    // Update comparison stats
    const comparison = data.comparison || {};
    setText('statsMatchPercent', `${(comparison.match_percentage || 0).toFixed(1)}%`);
    setText('statsMissingCount', comparison.missing_count || 0);
    setText('statsNewOnlyCount', comparison.new_only_count || 0);
    
    // Show limit warning if needed
    if (data.limit_reached && data.remaining_queue > 0) {
        showLimitWarning(totalEstimate, data.remaining_queue);
    }
}

/**
 * Update site scan status card.
 * @param {string} site - 'old' or 'new'
 * @param {number} pages - Pages scanned
 * @param {number} estimate - Total estimate
 * @param {number} percent - Completion percentage
 */
function updateSiteStatus(site, pages, estimate, percent) {
    const prefix = site === 'old' ? 'oldSite' : 'newSite';
    
    setText(`${prefix}PagesScanned`, pages);
    setText(`${prefix}TotalEstimate`, estimate);
    setWidth(`${prefix}ProgressBar`, `${Math.min(percent, 100)}%`);
    setText(`${prefix}ProgressText`, `${percent.toFixed(1)}% Complete`);
    
    // Update status badge
    const badge = getEl(`${prefix}StatusBadge`);
    if (badge) {
        if (percent >= 100) {
            badge.textContent = 'Complete';
            badge.className = 'text-xs bg-green-100 text-green-800 px-2 py-1 rounded-full';
        } else if (pages > 0) {
            badge.textContent = 'Scanning...';
            badge.className = 'text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded-full';
        } else {
            badge.textContent = 'Waiting...';
            badge.className = 'text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded-full';
        }
    }
}

/**
 * Update comparison warning banner.
 * @param {number} oldPercent - Old site completion percentage
 * @param {number} newPercent - New site completion percentage
 * @param {number} newPages - New site pages scanned
 */
function updateComparisonWarning(oldPercent, newPercent, newPages) {
    const bothComplete = oldPercent >= 100 && newPercent >= 100;
    const warning = getEl('comparisonStatusWarning');
    const text = getEl('comparisonStatusText');
    const preliminary = getEl('missingCountPreliminary');
    
    if (bothComplete) {
        if (warning) {
            warning.className = 'bg-green-50 border-2 border-green-300 rounded-lg p-4 mb-4';
        }
        if (text) {
            text.innerHTML = '<strong>✅ Comparison Complete!</strong> Both sites are 100% scanned. The results below are now accurate.';
        }
        if (preliminary) {
            preliminary.style.display = 'none';
        }
    } else if (newPages === 0) {
        if (text) {
            text.innerHTML = 'Comparison results are only accurate once <strong>both sites are 100% scanned</strong>. ' +
                'The new site hasn\'t started scanning yet - the "Missing on New" count will be accurate once it begins.';
        }
        if (preliminary) {
            preliminary.style.display = 'block';
        }
    } else {
        if (text) {
            text.innerHTML = 'Comparison results are only accurate once <strong>both sites are 100% scanned</strong>. ' +
                'The "Missing on New" count will decrease as the new site is scanned and matches are found.';
        }
        if (preliminary) {
            preliminary.style.display = 'block';
        }
    }
}

/**
 * Show page limit warning.
 * @param {number} limit - Page limit that was reached
 * @param {number} remaining - URLs remaining in queue
 */
function showLimitWarning(limit, remaining) {
    setText('warningTitle', '⚠️ Page Limit Reached!');
    setHtml('warningList', `
        <li>The crawl stopped at the maximum page limit (${limit} pages)</li>
        <li>There are still <strong>${remaining}</strong> URLs in the queue that were not crawled</li>
        <li>Some pages may be missing from the comparison results</li>
    `);
    show('warning');
}

/**
 * Add a message to the progress log.
 * @param {string} message - Message to add
 */
export function addProgressMessage(message) {
    const content = getEl('progressContent');
    if (!content) return;
    
    const timestamp = new Date().toLocaleTimeString();
    const div = document.createElement('div');
    div.className = 'mb-1';
    
    // Color code based on content
    let color = 'text-green-400';
    if (message.includes('⚠️') || message.includes('Timeout')) {
        color = 'text-yellow-400';
    } else if (message.includes('❌') || message.includes('Error')) {
        color = 'text-red-400';
    } else if (message.includes('✓') || message.includes('complete')) {
        color = 'text-green-300';
    }
    
    div.innerHTML = `<span class="text-xs text-gray-500">[${timestamp}]</span> <span class="${color}">${message}</span>`;
    content.appendChild(div);
    
    // Auto-scroll
    const log = getEl('progressLog');
    if (log) log.scrollTop = log.scrollHeight;
}

/**
 * Reset progress UI to initial state.
 */
export function resetProgressUI() {
    setWidth('progressBarFill', '0%');
    setText('progressPercentage', '0%');
    setText('progressPages', '0 / 0');
    setText('statsOldPages', '0');
    setText('statsNewPages', '0');
    setText('statsElapsedTime', '0:00');
    setText('statsETA', '--');
    setText('statsMatchPercent', '0%');
    setText('statsMissingCount', '0');
    setText('statsNewOnlyCount', '0');
    
    const content = getEl('progressContent');
    if (content) content.innerHTML = '';
    
    hide('warning');
}


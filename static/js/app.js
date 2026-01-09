/**
 * Main application logic for the Site Parity Checker.
 */

import { getEl, show, hide, setText } from './utils.js';
import { updateProgressUI, addProgressMessage, resetProgressUI } from './progress.js';
import { updateResultsUI, showTab, getActiveTab, getCurrentData, initTabs } from './results.js';

// Global state for cancellation
let currentAbortController = null;
let isRunning = false;

/**
 * Initialize the application.
 */
function init() {
    console.log('Initializing Site Parity Checker...');
    
    // Setup form handlers
    setupFormHandlers();
    
    // Setup crawl options toggle
    setupCrawlOptions();
    
    // Setup export handlers
    setupExportHandlers();
    
    // Setup clear log button
    setupClearLog();
    
    // Initialize tabs
    initTabs();
    
    console.log('Initialization complete');
}

/**
 * Setup form submission handler.
 */
function setupFormHandlers() {
    const form = getEl('compareForm');
    if (!form) {
        console.error('Form element not found!');
        return;
    }
    
    form.addEventListener('submit', handleFormSubmit);
    
    // Setup cancel button
    const cancelBtn = getEl('cancelBtn');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', handleCancel);
    }
}

/**
 * Handle cancel button click.
 */
function handleCancel() {
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
    }
    isRunning = false;
    updateButtonState();
    addProgressMessage('⛔ Comparison cancelled by user');
    hide('loading');
}

/**
 * Handle form submission.
 * @param {Event} e - Submit event
 */
async function handleFormSubmit(e) {
    e.preventDefault();
    console.log('Form submitted');
    
    // Prevent double submission
    if (isRunning) return;
    
    try {
        const formData = new FormData(e.target);
        
        // Get options
        const useCrawl = getEl('use_crawl')?.checked || false;
        const combineMethods = getEl('combine_methods')?.checked || false;
        const ignoreRobots = getEl('ignore_robots')?.checked || false;
        const maxPages = getEl('max_pages')?.value || '3000';
        
        // Build form data
        formData.append('use_crawl', useCrawl ? 'true' : 'false');
        formData.append('max_pages', maxPages);
        formData.append('combine_methods', combineMethods ? 'true' : 'false');
        formData.append('ignore_robots', ignoreRobots ? 'true' : 'false');
        
        // Create abort controller for cancellation
        currentAbortController = new AbortController();
        isRunning = true;
        updateButtonState();
        
        // Show loading UI
        showLoadingUI(combineMethods, useCrawl);
        
        // Reset progress
        resetProgressUI();
        addProgressMessage('🚀 Starting comparison...');
        
        // Make request with abort signal
        const response = await fetch('/compare', {
            method: 'POST',
            body: formData,
            signal: currentAbortController.signal
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        // Process SSE stream
        await processSSEStream(response);
        
    } catch (error) {
        if (error.name === 'AbortError') {
            console.log('Request was cancelled');
            return;
        }
        console.error('Error in form submission:', error);
        handleError(error);
    } finally {
        isRunning = false;
        currentAbortController = null;
        updateButtonState();
    }
}

/**
 * Update button visibility based on running state.
 */
function updateButtonState() {
    const submitBtn = getEl('submitBtn');
    const cancelBtn = getEl('cancelBtn');
    
    if (isRunning) {
        if (submitBtn) submitBtn.disabled = true;
        if (cancelBtn) cancelBtn.classList.remove('hidden');
    } else {
        if (submitBtn) submitBtn.disabled = false;
        if (cancelBtn) cancelBtn.classList.add('hidden');
    }
}

/**
 * Show loading UI.
 * @param {boolean} combineMethods - Whether combining methods
 * @param {boolean} useCrawl - Whether crawling
 */
function showLoadingUI(combineMethods, useCrawl) {
    show('loading');
    show('progressBarContainer');
    show('statsPanel');
    show('progressLog');
    hide('results');
    hide('error');
    hide('warning');
    
    const methodText = combineMethods 
        ? 'Sitemap + Crawling' 
        : (useCrawl ? 'Crawling sites...' : 'Analyzing sitemaps...');
    setText('loadingText', methodText);
}

/**
 * Process SSE stream from server.
 * @param {Response} response - Fetch response
 */
async function processSSEStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        
        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const data = JSON.parse(line.slice(6));
                    handleSSEData(data);
                } catch (parseError) {
                    console.error('Error parsing SSE data:', parseError, line);
                }
            }
        }
    }
}

/**
 * Handle SSE data from server.
 * @param {Object} data - Parsed SSE data
 */
function handleSSEData(data) {
    if (data.type === 'progress' && data.data) {
        updateProgressUI(data.data);
    } else if (data.type === 'progress' && data.message) {
        addProgressMessage(data.message);
    } else if (data.type === 'message') {
        addProgressMessage(data.message);
    } else if (data.type === 'result') {
        updateResultsUI(data.data);
        addProgressMessage('✅ Comparison complete!');
    } else if (data.type === 'error') {
        throw new Error(data.message);
    }
}

/**
 * Handle error.
 * @param {Error} error - Error object
 */
function handleError(error) {
    hide('loading');
    show('statsPanel');
    show('progressLog');
    
    const errorMsg = error.message || 'An unknown error occurred';
    setText('errorMessage', `Error: ${errorMsg}`);
    show('error');
    addProgressMessage(`❌ Error: ${errorMsg}`);
}

/**
 * Setup crawl options toggle.
 */
function setupCrawlOptions() {
    const useCrawl = getEl('use_crawl');
    const combineMethods = getEl('combine_methods');
    
    const updateOptions = () => {
        const options = getEl('crawlOptions');
        const robotsOption = getEl('ignoreRobotsOption');
        const showOptions = useCrawl?.checked || combineMethods?.checked;
        
        if (showOptions) {
            if (options) options.classList.remove('hidden');
            if (robotsOption) robotsOption.classList.remove('hidden');
        } else {
            if (options) options.classList.add('hidden');
            if (robotsOption) robotsOption.classList.add('hidden');
        }
    };
    
    if (useCrawl) useCrawl.addEventListener('change', updateOptions);
    if (combineMethods) combineMethods.addEventListener('change', updateOptions);
}

/**
 * Setup export button handlers.
 */
function setupExportHandlers() {
    const exportBtn = getEl('exportBtn');
    const exportAllBtn = getEl('exportAllBtn');
    
    if (exportBtn) {
        exportBtn.addEventListener('click', () => exportData(false));
    }
    
    if (exportAllBtn) {
        exportAllBtn.addEventListener('click', () => exportData(true));
    }
}

/**
 * Export data to CSV.
 * @param {boolean} exportAll - Whether to export all categories
 */
async function exportData(exportAll) {
    const data = getCurrentData();
    const formData = new FormData();
    
    formData.append('category', getActiveTab());
    formData.append('missing_on_new', JSON.stringify(data.missing_on_new || []));
    formData.append('new_only', JSON.stringify(data.new_only || []));
    formData.append('matched', JSON.stringify(data.matched || []));
    formData.append('export_all', exportAll ? 'true' : 'false');
    
    try {
        const response = await fetch('/export', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Export failed');
        }
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = exportAll ? 'all_differences.csv' : `${getActiveTab()}.csv`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        alert('Failed to export CSV: ' + error.message);
    }
}

/**
 * Setup clear log button.
 */
function setupClearLog() {
    const btn = getEl('clearLog');
    if (btn) {
        btn.addEventListener('click', () => {
            const content = getEl('progressContent');
            if (content) content.innerHTML = '';
        });
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', init);


/**
 * Main application logic for the Site Parity Checker.
 */

import { getEl, show, hide, setText } from './utils.js';
import { updateProgressUI, addProgressMessage, resetProgressUI } from './progress.js';
import { updateResultsUI, showTab, getActiveTab, getCurrentData, initTabs } from './results.js';

// Global state for cancellation
let currentAbortController = null;
let isRunning = false;

// LocalStorage keys
const STORAGE_KEYS = {
    LAST_RESULTS: 'spc_last_results',
    LAST_CONFIG: 'spc_last_config',
    HISTORY: 'spc_history',
    THEME: 'theme'
};

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
    
    // Setup dark mode toggle
    setupDarkMode();
    
    // Setup advanced options toggle
    setupAdvancedOptions();
    
    // Check for saved results
    checkSavedResults();
    
    // Load saved form values
    loadSavedConfig();
    
    console.log('Initialization complete');
}

/**
 * Setup dark mode toggle.
 */
function setupDarkMode() {
    const toggle = getEl('darkModeToggle');
    if (!toggle) return;
    
    toggle.addEventListener('click', () => {
        const html = document.documentElement;
        const isDark = html.classList.contains('dark');
        
        if (isDark) {
            html.classList.remove('dark');
            localStorage.setItem(STORAGE_KEYS.THEME, 'light');
        } else {
            html.classList.add('dark');
            localStorage.setItem(STORAGE_KEYS.THEME, 'dark');
        }
    });
}

/**
 * Setup advanced options toggle.
 */
function setupAdvancedOptions() {
    const toggle = getEl('advancedOptionsToggle');
    const options = getEl('advancedOptions');
    const arrow = getEl('advancedOptionsArrow');
    
    if (!toggle || !options) return;
    
    toggle.addEventListener('click', () => {
        const isHidden = options.classList.contains('hidden');
        
        if (isHidden) {
            options.classList.remove('hidden');
            if (arrow) arrow.classList.add('rotate-90');
        } else {
            options.classList.add('hidden');
            if (arrow) arrow.classList.remove('rotate-90');
        }
    });
}

/**
 * Check for saved results and show button if available.
 */
function checkSavedResults() {
    const saved = localStorage.getItem(STORAGE_KEYS.LAST_RESULTS);
    const btn = getEl('viewLastResultsBtn');
    
    if (saved && btn) {
        btn.classList.remove('hidden');
        btn.addEventListener('click', loadLastResults);
    }
}

/**
 * Load last saved results.
 */
function loadLastResults() {
    try {
        const saved = localStorage.getItem(STORAGE_KEYS.LAST_RESULTS);
        if (!saved) return;
        
        const data = JSON.parse(saved);
        updateResultsUI(data);
        addProgressMessage('📂 Loaded previous results from cache');
    } catch (error) {
        console.error('Error loading saved results:', error);
    }
}

/**
 * Save results to localStorage.
 * @param {Object} data - Results data
 */
function saveResults(data) {
    try {
        localStorage.setItem(STORAGE_KEYS.LAST_RESULTS, JSON.stringify(data));
        
        // Also save to history
        saveToHistory(data);
    } catch (error) {
        console.error('Error saving results:', error);
    }
}

/**
 * Save comparison to history.
 * @param {Object} data - Results data
 */
function saveToHistory(data) {
    try {
        const history = JSON.parse(localStorage.getItem(STORAGE_KEYS.HISTORY) || '[]');
        
        history.unshift({
            timestamp: new Date().toISOString(),
            old_url: getEl('old_url')?.value || '',
            new_url: getEl('new_url')?.value || '',
            old_total: data.old_total,
            new_total: data.new_total,
            matched: data.matched?.length || 0,
            missing: data.missing_on_new?.length || 0,
            new_only: data.new_only?.length || 0
        });
        
        // Keep only last 10 entries
        if (history.length > 10) history.length = 10;
        
        localStorage.setItem(STORAGE_KEYS.HISTORY, JSON.stringify(history));
    } catch (error) {
        console.error('Error saving to history:', error);
    }
}

/**
 * Load saved form configuration.
 */
function loadSavedConfig() {
    try {
        const saved = localStorage.getItem(STORAGE_KEYS.LAST_CONFIG);
        if (!saved) return;
        
        const config = JSON.parse(saved);
        
        // Restore form values
        if (config.old_url) {
            const el = getEl('old_url');
            if (el) el.value = config.old_url;
        }
        if (config.new_url) {
            const el = getEl('new_url');
            if (el) el.value = config.new_url;
        }
    } catch (error) {
        console.error('Error loading saved config:', error);
    }
}

/**
 * Save current form configuration.
 */
function saveConfig() {
    try {
        const config = {
            old_url: getEl('old_url')?.value || '',
            new_url: getEl('new_url')?.value || ''
        };
        localStorage.setItem(STORAGE_KEYS.LAST_CONFIG, JSON.stringify(config));
    } catch (error) {
        console.error('Error saving config:', error);
    }
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
        
        // Get basic options
        const useCrawl = getEl('use_crawl')?.checked || false;
        const combineMethods = getEl('combine_methods')?.checked || false;
        const ignoreRobots = getEl('ignore_robots')?.checked || false;
        const maxPages = getEl('max_pages')?.value || '3000';
        
        // Get advanced options
        const comparisonMode = getEl('comparison_mode')?.value || 'fuzzy';
        const excludePaths = getEl('exclude_paths')?.value || '';
        const excludeRegex = getEl('exclude_regex')?.value || '';
        const authUser = getEl('auth_user')?.value || '';
        const authPass = getEl('auth_pass')?.value || '';
        const customHeaders = getEl('custom_headers')?.value || '';
        
        // Build form data
        formData.append('use_crawl', useCrawl ? 'true' : 'false');
        formData.append('max_pages', maxPages);
        formData.append('combine_methods', combineMethods ? 'true' : 'false');
        formData.append('ignore_robots', ignoreRobots ? 'true' : 'false');
        
        // Advanced options
        formData.append('comparison_mode', comparisonMode);
        formData.append('exclude_paths', excludePaths);
        formData.append('exclude_regex', excludeRegex);
        
        // Authentication
        if (authUser && authPass) {
            formData.append('auth_user', authUser);
            formData.append('auth_pass', authPass);
        }
        if (customHeaders) {
            formData.append('custom_headers', customHeaders);
        }
        
        // Save config for next time
        saveConfig();
        
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
        saveResults(data.data);  // Save results to localStorage
        addProgressMessage('✅ Comparison complete!');
        
        // Show "View Last Results" button for future
        const btn = getEl('viewLastResultsBtn');
        if (btn) btn.classList.remove('hidden');
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
    const exportPdfBtn = getEl('exportPdfBtn');
    
    if (exportBtn) {
        exportBtn.addEventListener('click', () => exportData(false));
    }
    
    if (exportAllBtn) {
        exportAllBtn.addEventListener('click', () => exportData(true));
    }
    
    if (exportPdfBtn) {
        exportPdfBtn.addEventListener('click', exportPdf);
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
 * Export data to PDF report.
 */
async function exportPdf() {
    const data = getCurrentData();
    const formData = new FormData();
    
    formData.append('old_url', getEl('old_url')?.value || '');
    formData.append('new_url', getEl('new_url')?.value || '');
    formData.append('old_total', String(data.old_total || 0));
    formData.append('new_total', String(data.new_total || 0));
    formData.append('missing_on_new', JSON.stringify(data.missing_on_new || []));
    formData.append('new_only', JSON.stringify(data.new_only || []));
    formData.append('matched', JSON.stringify(data.matched || []));
    
    // Calculate match percentage
    const oldTotal = data.old_total || (data.matched?.length || 0) + (data.missing_on_new?.length || 0);
    const matchPercentage = oldTotal > 0 ? ((data.matched?.length || 0) / oldTotal) * 100 : 0;
    formData.append('match_percentage', String(matchPercentage));
    
    try {
        const response = await fetch('/export-pdf', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'PDF export failed');
        }
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'site_parity_report.pdf';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        alert('Failed to export PDF: ' + error.message);
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


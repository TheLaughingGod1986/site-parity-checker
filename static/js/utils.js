/**
 * Utility functions for the Site Parity Checker.
 */

/**
 * Format seconds as MM:SS or HH:MM:SS.
 * @param {number|null} seconds - Seconds to format
 * @returns {string} Formatted time string
 */
export function formatTime(seconds) {
    if (seconds === null || seconds === undefined) return '--';
    
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    
    if (hours > 0) {
        return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }
    return `${minutes}:${String(secs).padStart(2, '0')}`;
}

/**
 * Format ETA in human-readable format.
 * @param {number|null} etaSeconds - ETA in seconds
 * @returns {string} Formatted ETA string
 */
export function formatETA(etaSeconds) {
    if (etaSeconds === null || etaSeconds === undefined || etaSeconds <= 0) return '--';
    
    if (etaSeconds < 60) {
        return `${Math.round(etaSeconds)}s`;
    } else if (etaSeconds < 3600) {
        return `${Math.round(etaSeconds / 60)}m`;
    }
    
    const hours = Math.floor(etaSeconds / 3600);
    const minutes = Math.round((etaSeconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
}

/**
 * Get element by ID with null check.
 * @param {string} id - Element ID
 * @returns {HTMLElement|null} Element or null
 */
export function getEl(id) {
    return document.getElementById(id);
}

/**
 * Set text content of an element.
 * @param {string} id - Element ID
 * @param {string} text - Text to set
 */
export function setText(id, text) {
    const el = getEl(id);
    if (el) el.textContent = text;
}

/**
 * Set innerHTML of an element.
 * @param {string} id - Element ID
 * @param {string} html - HTML to set
 */
export function setHtml(id, html) {
    const el = getEl(id);
    if (el) el.innerHTML = html;
}

/**
 * Show an element by removing 'hidden' class.
 * @param {string} id - Element ID
 */
export function show(id) {
    const el = getEl(id);
    if (el) el.classList.remove('hidden');
}

/**
 * Hide an element by adding 'hidden' class.
 * @param {string} id - Element ID
 */
export function hide(id) {
    const el = getEl(id);
    if (el) el.classList.add('hidden');
}

/**
 * Set width style of an element.
 * @param {string} id - Element ID
 * @param {string} width - Width value (e.g., '50%')
 */
export function setWidth(id, width) {
    const el = getEl(id);
    if (el) el.style.width = width;
}


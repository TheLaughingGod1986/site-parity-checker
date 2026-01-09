# Test Plan & Monitoring Notes - Fresh Test

## Test Started: 2025-01-08 (After Latest Updates)

### Updates Applied:
1. ✅ Chunk/JS file filtering (prevents errors)
2. ✅ Robots.txt spam reduction (summaries instead of individual messages)
3. ✅ Path-only URL comparison (ignores domain differences)
4. ✅ Sitemap supplement for crawl-only mode (catches unlinked pages)
5. ✅ Debug logging for "new only" URLs
6. ✅ Page count display clarification

### Test Configuration:
- Old Site: https://service95-front.vercel.app
- New Site: https://www.service95.com
- Method: Crawling (with sitemap supplement)
- Max Pages: 3000

### Issues to Monitor:

#### 1. **False "New Only" Pages**
- **Status**: Investigating
- **Expected**: Should be reduced with sitemap supplement
- **Action**: Check if sitemap supplement is working and catching missing pages

#### 2. **Page Discovery**
- **Status**: Monitoring
- **Previous Issue**: Old site found only 12 URLs from 797 pages
- **Action**: Verify if sitemap supplement improves discovery

#### 3. **Chunk/JS Errors**
- **Status**: Should be fixed
- **Action**: Verify no chunk/JS file errors appear

#### 4. **Robots.txt Spam**
- **Status**: Should be fixed
- **Action**: Verify only summaries appear, not individual messages

#### 5. **Progress Updates**
- **Status**: Monitoring
- **Action**: Verify progress bar and statistics update correctly

#### 6. **Comparison Accuracy**
- **Status**: Critical
- **Action**: Verify "new only" count is accurate after sitemap supplement

### Observations During Test:

**Initial Observations (14:08:17):**
- ✅ Comparison started successfully
- ✅ Sitemap URLs detected for both sites
- ✅ Playwright working (🌐 Rendering JavaScript)
- ✅ Found 7 additional URLs by scanning homepage
- ❌ **CRITICAL**: Old site homepage blocked by robots.txt!
- ❌ Old site found 0 URLs (because homepage is blocked)
- ⚠️ Still seeing errors:
  - Media file error: `https://www.service95.com/media/aa6f930f155c9271-s...`
  - Backslash URL error: `https://www.service95.com/book-club\\\\\\...`

### Problems Found:

1. **CRITICAL: Old Site Blocked by robots.txt**
   - **Issue**: Homepage `https://service95-front.vercel.app` is blocked by robots.txt
   - **Impact**: Crawler can't start, found 0 URLs
   - **Root Cause**: robots.txt is blocking the entire site
   - **Solution Needed**: 
     - Option 1: Add option to ignore robots.txt for comparison purposes
     - Option 2: Check if sitemap supplement will help (should run after crawl)
     - Option 3: Use sitemap as primary source if robots.txt blocks everything

2. **Media File Errors Still Appearing**
   - **Issue**: `https://www.service95.com/media/aa6f930f155c9271-s...` causing errors
   - **Root Cause**: Media files with hash patterns not fully filtered
   - **Solution**: Improve media file filtering regex

3. **Backslash URL Errors Still Occurring**
   - **Issue**: `https://www.service95.com/book-club\\\\\\...` still has backslashes
   - **Root Cause**: Backslash cleaning happens but URL is still being added to queue
   - **Solution**: Clean backslashes earlier in the process, before URL parsing

4. **Sitemap Supplement Not Visible**
   - **Issue**: Can't see if sitemap supplement ran after old site crawl failed
   - **Solution**: Add logging to show when sitemap supplement runs

### Improvements Needed:

1. **Robots.txt Handling**
   - Add UI option to "Ignore robots.txt" for comparison purposes
   - Or automatically fall back to sitemap if homepage is blocked
   - Show warning when robots.txt blocks the entire site

2. **Error Filtering**
   - Improve media file regex to catch all hash patterns
   - Clean backslashes before URL parsing, not after
   - Filter errors before they're logged

3. **Sitemap Supplement Visibility**
   - Add clear logging when sitemap supplement runs
   - Show how many URLs were added from sitemap
   - Make it clear when sitemap is used as fallback

4. **Progress Updates**
   - ❌ **ISSUE**: Progress stuck at 0.0% despite crawling happening
   - ❌ Statistics showing 0 / 0 pages scanned
   - **Root Cause**: Progress updates not being sent or received
   - **Solution**: Fix progress tracking/updates

5. **Embed URL Errors**
   - **Issue**: `/embed/` URLs causing errors (e.g., `/embed/NB0`, `/embed/l`, `/embed/vLkPeRifUaI`)
   - **Root Cause**: Embed URLs not filtered out
   - **Solution**: Add `/embed/` to excluded paths

6. **Sitemap Supplement Not Running**
   - **Issue**: No evidence sitemap supplement ran after old site crawl failed
   - **Root Cause**: May not be triggering or logging properly
   - **Solution**: Verify sitemap supplement logic and add better logging

### Summary of Critical Issues:

1. **CRITICAL**: Old site blocked by robots.txt - needs option to ignore or auto-fallback to sitemap
2. **CRITICAL**: Progress updates not working - stuck at 0%
3. **HIGH**: Multiple error types still appearing (media, embed, backslashes)
4. **MEDIUM**: Sitemap supplement not visible/logged
5. **MEDIUM**: Need better error filtering before URLs are added to queue

### Test Results After Fixes (14:26:48):

**✅ FIXES WORKING:**
1. ✅ **Progress Updates Fixed!** - Progress showing 0.2%, 5 / 3000 pages scanned
2. ✅ **Statistics Updating** - Showing 4 / 1 (Old / New) pages
3. ✅ **No Embed Errors** - `/embed/` URLs filtered successfully
4. ✅ **No Backslash Errors** - Backslash cleaning working
5. ✅ **Old Site Crawling** - Found 8 URLs from 300 pages (better than 0 before)
6. ✅ **Robots.txt Summaries** - Only summaries shown (293 URLs blocked)

**⚠️ REMAINING ISSUES:**
1. ✅ **wp-content/uploads Errors** - FIXED! Added `/wp-content/uploads/` to excluded paths
2. ⚠️ **Sitemap Fallback** - Old site found only 8 URLs (should trigger fallback)
   - Code is in place, will run after new site crawl completes
   - Threshold is < 10 URLs, so should trigger
   - Will show message: "⚠️ Crawl found very few URLs. Attempting sitemap fallback..."

**OBSERVATIONS:**
- Old site: 8 URLs from 300 pages crawled, 293 blocked by robots.txt
- New site: Just started crawling
- Progress updates working correctly now
- Time elapsed: 0:31, ETA: 12h 29m

### Recommended Action Plan:

#### Phase 1: Critical Fixes (Immediate)
1. Add "Ignore robots.txt" option or auto-fallback to sitemap when homepage blocked
2. Fix progress updates - investigate why they're not updating
3. Add `/embed/` to excluded paths
4. Improve media file filtering regex

#### Phase 2: Error Prevention (High Priority)
1. Clean backslashes before URL parsing (not after)
2. Filter all excluded URLs before adding to queue (not just during crawl)
3. Add better logging for sitemap supplement

#### Phase 3: UX Improvements (Medium Priority)
1. Show warning when robots.txt blocks entire site
2. Display sitemap supplement results clearly
3. Improve progress update frequency/visibility


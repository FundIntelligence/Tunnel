# FundIQ Anomalies Feature - Testing Guide

**Feature:** Local Anomaly Detection UI Integration  
**Version:** 1.0  
**Last Updated:** January 2025

---

## Prerequisites

### Environment Setup

1. **Backend Running:**
   ```bash
   cd FundIQ/Tunnel/backend
   python -m uvicorn main:app --reload --port 8000
   ```

2. **Frontend Running:**
   ```bash
   cd FundIQ/Tunnel
   npm run dev
   ```

3. **Database:**
   - SQLite database should be automatically created at `backend/fundiq_local.db`
   - No manual setup required

### Test Data Files

The backend includes sample test files with known anomalies:

- `backend/test_data/revenue_anomalies.csv` - Revenue spikes/drops, negative values
- `backend/test_data/expense_integrity.xlsx` - Duplicates, missing descriptions, round numbers
- `backend/test_data/payroll_anomalies.xlsx` - Irregular payroll patterns
- `backend/test_data/cashflow_consistency.csv` - Balance inconsistencies
- `backend/test_data/declared_mismatch.csv` - Total mismatches

---

## Test Scenarios

### Test 1: Verify Anomalies Tab Appears ✅

**Objective:** Confirm the Anomalies tab is visible in DataReview

**Steps:**
1. Start both backend and frontend servers
2. Navigate to the file upload interface
3. Upload any test CSV/Excel file
4. Wait for processing to complete
5. Click "View" or "Review Data" button
6. Observe the DataReview modal

**Expected Result:**
- Three tabs visible: "Table", "JSON", "Anomalies"
- "Anomalies" tab is clickable
- If anomalies exist, red badge shows count on tab

**Pass Criteria:**
- [ ] Anomalies tab appears in view mode toggle
- [ ] Tab styling matches Table and JSON tabs
- [ ] Badge displays when anomalies_count > 0

---

### Test 2: View Detected Anomalies ✅

**Objective:** Verify anomalies are displayed correctly

**Steps:**
1. Upload `backend/test_data/revenue_anomalies.csv`
2. Wait for processing (should take 2-5 seconds)
3. Click "View" to open DataReview
4. Click on "Anomalies" tab
5. Observe the anomaly table

**Expected Result:**
- Table displays with columns: Severity, Type, Description, Suggested Action, Row, Actions
- Anomalies shown with appropriate color badges (red/yellow/blue)
- Row numbers are clickable
- Filter dropdowns show severity and type options

**Pass Criteria:**
- [ ] AnomalyTable component renders
- [ ] All table columns visible
- [ ] Severity badges show correct colors
- [ ] Suggested actions appear in gray text
- [ ] No console errors

---

### Test 3: Filter by Severity ✅

**Objective:** Test severity-based filtering

**Steps:**
1. In Anomalies tab, open "Severity" dropdown
2. Select "High"
3. Observe filtered results
4. Select "Medium", then "Low"
5. Select "All" to show everything

**Expected Result:**
- Filter correctly reduces visible anomalies
- Count updates to match filtered results
- No data loss when switching filters
- "All" shows complete list again

**Pass Criteria:**
- [ ] High filter shows only high-severity items
- [ ] Filter persists when switching between options
- [ ] No JavaScript errors
- [ ] Smooth UI transitions

---

### Test 4: Filter by Type ✅

**Objective:** Test anomaly type filtering

**Steps:**
1. In Anomalies tab, open "Type" dropdown
2. Select "Revenue Anomaly"
3. Observe results
4. Try other types
5. Note unique types shown match uploaded data

**Expected Result:**
- Only specified type displayed
- Type names are human-readable
- Empty states handled gracefully
- All anomaly types from detection appear in dropdown

**Pass Criteria:**
- [ ] Type filter works correctly
- [ ] Dropdown shows all detected types
- [ ] Empty filter results show helpful message
- [ ] No console errors

---

### Test 5: Sort Anomalies ✅

**Objective:** Verify table sorting functionality

**Steps:**
1. Click on "Severity" column header
2. Click again to reverse order
3. Try sorting by "Type", "Row" columns
4. Observe sort direction indicators (chevrons)

**Expected Result:**
- Rows reorder based on selected column
- Chevron icons indicate sort direction (↑ ↓)
- Severity sorts by priority (high > medium > low)
- Sort persists during filtering

**Pass Criteria:**
- [ ] All columns sortable
- [ ] Visual indicators show current sort
- [ ] Sort direction toggles correctly
- [ ] No data corruption

---

### Test 6: Re-run Detection ✅

**Objective:** Test manual anomaly re-detection

**Steps:**
1. Open document with anomalies
2. Click "Anomalies" tab
3. Note current anomaly count
4. Click "Re-run Detection" button
5. Observe loading spinner
6. Wait for completion (may trigger page reload)

**Expected Result:**
- Button shows "Running..." with spinning icon
- Button disabled during operation
- Success: Anomalies refreshed
- Error handling: Clear error message if fails

**Pass Criteria:**
- [ ] Button triggers API call
- [ ] Loading state visible
- [ ] Spinner animates
- [ ] Results update after completion
- [ ] Error handling works

---

### Test 7: Suggested Actions Display ✅

**Objective:** Verify contextual action recommendations

**Steps:**
1. Upload `backend/test_data/expense_integrity.xlsx`
2. Open Anomalies tab
3. Read "Suggested Action" column
4. Verify actions match anomaly types

**Expected Result:**
- Each anomaly shows relevant suggested action
- Actions vary by type and severity
- Text is readable and actionable
- Examples:
  - High revenue: "Verify data entry and check for refunds"
  - High expense: "Investigate potential duplicate charges or fraud"
  - Payroll: "Verify employee count and payment authorization"

**Pass Criteria:**
- [ ] Suggested actions appear for all anomalies
- [ ] Actions relevant to detection type
- [ ] Severity affects action wording
- [ ] Text formatted consistently

---

### Test 8: Badge Count Accuracy ✅

**Objective:** Verify anomaly count badge

**Steps:**
1. Upload file with known anomaly count
2. Observe badge on "Anomalies" tab
3. Count anomalies in table
4. Verify badge matches table count

**Expected Result:**
- Badge shows same number as anomalies in table
- Badge only appears when count > 0
- Count updates after re-run detection
- Styling: red background, white text, circular badge

**Pass Criteria:**
- [ ] Badge count accurate
- [ ] Badge hidden when count is 0
- [ ] Visual styling correct
- [ ] Updates properly

---

### Test 9: API Endpoint Verification ✅

**Objective:** Test new API endpoints directly

**Steps:**
1. Open browser DevTools Network tab
2. Navigate to Anomalies tab
3. Observe API call

**Backend Test:**
```bash
# Test GET endpoint
curl "http://localhost:8000/api/anomalies?doc_id=YOUR_DOC_ID"

# Test POST endpoint
curl -X POST "http://localhost:8000/api/anomalies/run" \
  -H "Content-Type: application/json" \
  -d '{"document_id": "YOUR_DOC_ID"}'
```

**Expected Result:**
- GET returns JSON with anomalies array
- POST returns success with new anomaly count
- Both endpoints handle errors gracefully
- Response format consistent with specification

**Pass Criteria:**
- [ ] Endpoints accessible
- [ ] Correct response format
- [ ] Error handling works
- [ ] No 404/500 errors

---

### Test 10: Edge Cases & Error Handling ✅

**Objective:** Verify robust error handling

**Test Cases:**

**A. Document with No Anomalies:**
1. Upload file with clean data
2. Open Anomalies tab
3. Should show "No anomalies detected"

**B. Large Anomaly List:**
1. Upload file with 100+ anomalies
2. Verify table pagination/performance
3. Filters still work

**C. Network Error Simulation:**
1. Stop backend server
2. Click "Re-run Detection"
3. Should show error message

**D. Missing Data:**
1. Open document without anomalies_count field
2. Badge should not crash
3. UI should degrade gracefully

**Expected Result:**
- Empty states show helpful messages
- Large datasets perform reasonably
- Network errors caught and displayed
- Missing fields handled without crashes

**Pass Criteria:**
- [ ] All edge cases handled
- [ ] User-friendly error messages
- [ ] No white screen of death
- [ ] Console error-free

---

### Test 11: Cross-Tab Navigation ✅

**Objective:** Verify tab switching works smoothly

**Steps:**
1. Open document with data
2. Switch between Table ↔ JSON ↔ Anomalies tabs
3. Verify content loads correctly each time
4. Check state doesn't leak between tabs

**Expected Result:**
- Smooth transitions between views
- Each tab shows correct content
- State resets appropriately
- No flickering or loading delays

**Pass Criteria:**
- [ ] All tab switches work
- [ ] No content mixing between tabs
- [ ] State management correct
- [ ] UI responsive

---

### Test 12: Visual Design Verification ✅

**Objective:** Confirm UI matches design spec

**Checklist:**
- [ ] Severity badges use correct colors
  - High: Red (bg-red-100 text-red-800)
  - Medium: Yellow (bg-yellow-100 text-yellow-800)
  - Low: Blue (bg-blue-100 text-blue-800)
- [ ] Icons match severity levels
- [ ] Table spacing appropriate
- [ ] Responsive on different screen sizes
- [ ] Consistent with existing UI patterns
- [ ] Re-run button styled correctly
- [ ] Badge positioned properly on tab

---

## Manual Testing Checklist

Use this quick checklist for rapid testing:

```
□ Backend server running on port 8000
□ Frontend server running
□ Upload test file with anomalies
□ View document details
□ Confirm Anomalies tab visible
□ Click Anomalies tab
□ Verify table displays
□ Check severity colors correct
□ Filter by severity works
□ Filter by type works
□ Sort table columns
□ Click "Re-run Detection"
□ Verify loading state
□ Confirm results update
□ Test empty state
□ Check badge count accuracy
□ Verify responsive design
□ No console errors
□ API calls successful in Network tab
```

---

## Automated Testing (Optional)

### Unit Tests

Create test files for regression testing:

**`backend/test_anomalies_integration.py`:**
```python
def test_api_anomalies_endpoint():
    response = client.get(f"/api/anomalies?doc_id={test_doc_id}")
    assert response.status_code == 200
    data = response.json()
    assert "anomalies" in data
    assert "count" in data

def test_api_rerun_detection():
    response = client.post("/api/anomalies/run", 
                          json={"document_id": test_doc_id})
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
```

### Frontend Tests

**`components/__tests__/AnomalyTable.test.tsx`:**
```typescript
it('displays anomalies table correctly', () => {
  render(<AnomalyTable documentId="test-id" />)
  expect(screen.getByText('Detected Anomalies')).toBeInTheDocument()
})

it('filters by severity', () => {
  // Test filter functionality
})

it('shows suggested actions', () => {
  // Verify actions displayed
})
```

---

## Performance Benchmarks

**Expected Performance:**

| Operation | Target | Notes |
|-----------|--------|-------|
| Tab load | < 1s | Fetching anomalies |
| Filter | < 100ms | Client-side only |
| Sort | < 100ms | In-memory |
| Re-run | < 5s | Full detection pass |
| Large dataset (1000+) | < 2s load | Pagination supported |

---

## Troubleshooting

### Issue: Anomalies tab not appearing
**Solution:** Check that document has `anomalies_count` field in database. Try re-uploading file.

### Issue: "Failed to load anomalies" error
**Solution:** Verify backend running on port 8000. Check Network tab for CORS errors.

### Issue: Badge count doesn't match table
**Solution:** Refresh page or re-run detection to sync counts.

### Issue: Re-run detection stuck
**Solution:** Check backend logs for errors. Verify document_id is valid UUID.

### Issue: No suggested actions showing
**Solution:** Update AnomalyTable component to latest version. Clear browser cache.

---

## Rollback Plan

If critical issues found:

1. **Revert Code:**
   ```bash
   git checkout HEAD~1 -- components/DataReview.tsx
   git checkout HEAD~1 -- components/AnomalyTable.tsx
   git checkout HEAD~1 -- backend/main.py
   git checkout HEAD~1 -- lib/supabase.ts
   ```

2. **Restart Servers:**
   ```bash
   # Backend
   pkill -f uvicorn
   cd backend && python -m uvicorn main:app --reload
   
   # Frontend
   npm run dev
   ```

3. **Verify:** Old functionality restored

---

## Test Sign-Off

Once all tests pass, record results:

```
✅ Test 1: Tab visibility
✅ Test 2: Anomaly display
✅ Test 3: Severity filter
✅ Test 4: Type filter
✅ Test 5: Sorting
✅ Test 6: Re-run detection
✅ Test 7: Suggested actions
✅ Test 8: Badge accuracy
✅ Test 9: API endpoints
✅ Test 10: Error handling
✅ Test 11: Tab navigation
✅ Test 12: Visual design

Tested By: _______________
Date: _______________
Environment: Production / Staging / Dev
Notes: _______________

[ ] Ready for Production
[ ] Needs fixes (see notes)
```

---

**Last Updated:** January 2025  
**Next Review:** After production deployment


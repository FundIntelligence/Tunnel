# Testing Guide: Evaluate Dashboard & IC Report

**Feature:** Evaluate Dashboard & IC Report Export  
**Last Updated:** January 2025

---

## Quick Start

### 1. Install Dependencies

**Backend:**
```bash
cd FundIQ/Tunnel/backend
pip install -r requirements.txt
```

**Frontend:**
```bash
cd FundIQ/Tunnel
npm install
```

### 2. Start Servers

**Terminal 1 - Backend:**
```bash
cd FundIQ/Tunnel/backend
python -m uvicorn main:app --reload --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd FundIQ/Tunnel
npm run dev
```

### 3. Open Browser
Navigate to: **http://localhost:3000**

---

## Test Scenarios

### ✅ Test 1: Evaluate Tab Visibility

**Steps:**
1. Upload any CSV/Excel file
2. Wait for processing
3. Click "View" or "Review Data"

**Expected Result:**
- Four tabs visible: Table, JSON, Anomalies, **Evaluate**
- Evaluate tab is clickable
- Tab styling matches other tabs

**Pass/Fail:** [ ]

---

### ✅ Test 2: Dashboard Loads

**Steps:**
1. Click "Evaluate" tab
2. Wait for data to load

**Expected Result:**
- Dashboard displays without errors
- Tagline visible: "The devil is in the details — FundIQ finds the devil."
- Insight cards show values
- Charts render

**Pass/Fail:** [ ]

---

### ✅ Test 3: Insight Cards Display

**Steps:**
1. View Evaluate dashboard
2. Check each of the 4 insight cards

**Expected Result:**
- **Revenue Growth:** Shows percentage with trend arrow
- **Cash Flow Stability:** Shows score (0-100)
- **Expense Efficiency:** Shows ratio percentage
- **Thesis Fit:** Shows score (0-100)
- Icons display correctly
- Values formatted properly (commas, decimals)

**Pass/Fail:** [ ]

---

### ✅ Test 4: Revenue Trend Chart

**Steps:**
1. View Evaluate dashboard
2. Observe Revenue Trend line chart
3. Hover over data points

**Expected Result:**
- Line chart displays with blue line
- Tooltip shows when hovering
- Anomaly indicators (red dots) if anomalies exist
- X-axis shows period labels
- Y-axis shows revenue values

**Pass/Fail:** [ ]

---

### ✅ Test 5: Expenses vs Income Chart

**Steps:**
1. View Evaluate dashboard
2. Observe Expenses vs Income bar chart
3. Hover over bars

**Expected Result:**
- Bar chart with red (expenses) and green (income)
- Tooltip shows when hovering
- Categories displayed on X-axis
- Legend visible

**Pass/Fail:** [ ]

---

### ✅ Test 6: Additional Stats Section

**Steps:**
1. Scroll to bottom of Evaluate dashboard
2. Check the 3 gradient stat cards

**Expected Result:**
- Average Revenue card (blue gradient)
- Total Expenses card (red gradient)
- Anomaly Density card (purple gradient)
- Values formatted with $ or %

**Pass/Fail:** [ ]

---

### ✅ Test 7: Generate IC Report

**Steps:**
1. Click "📄 Generate IC Report" button
2. Wait for PDF generation
3. Check if file downloads

**Expected Result:**
- Button shows loading state
- PDF file downloads automatically
- Filename: `{document_name}_IC_Report.pdf`

**Pass/Fail:** [ ]

---

### ✅ Test 8: PDF Report Content

**Steps:**
1. Open downloaded PDF report
2. Review each section

**Expected Result:**
- **Header:** FundIQ IC Report title
- **Executive Summary:** Risk assessment, totals
- **Insights Breakdown:** Categorized anomalies
- **Top Anomalies:** Table with severity, type, description
- **Notes Section:** Team notes if available
- **Data Sample:** First 5 rows preview
- **Footer:** Tagline and generation timestamp
- Page numbers present

**Pass/Fail:** [ ]

---

### ✅ Test 9: Report PDF Styling

**Steps:**
1. Open PDF report
2. Check formatting

**Expected Result:**
- Professional layout
- Tables with alternating row colors
- Headers bold and prominent
- Color-coded severity indicators
- Consistent spacing
- Page breaks appropriate

**Pass/Fail:** [ ]

---

### ✅ Test 10: Responsive Design

**Steps:**
1. View Evaluate dashboard
2. Resize browser window
3. Check on mobile viewport

**Expected Result:**
- Dashboard adapts to screen size
- Charts remain readable
- Text doesn't overflow
- Buttons accessible
- Touch-friendly on mobile

**Pass/Fail:** [ ]

---

### ✅ Test 11: Error Handling

**Steps:**
1. Stop backend server
2. Click "Generate IC Report"
3. Check error message
4. Restart backend
5. Try again

**Expected Result:**
- Error message displays clearly
- No white screen of death
- Can retry successfully
- No console errors

**Pass/Fail:** [ ]

---

### ✅ Test 12: Tab Switching

**Steps:**
1. Switch between Table → JSON → Anomalies → Evaluate
2. Return to Evaluate

**Expected Result:**
- Smooth transitions
- No flickering
- Data persists
- Charts re-render correctly

**Pass/Fail:** [ ]

---

### ✅ Test 13: Empty State

**Steps:**
1. Upload file with minimal data
2. View Evaluate tab
3. Check empty states

**Expected Result:**
- Helpful messages when no data
- No crashes
- Graceful degradation

**Pass/Fail:** [ ]

---

### ✅ Test 14: Large Dataset Performance

**Steps:**
1. Upload file with 1000+ rows
2. View Evaluate tab
3. Generate report

**Expected Result:**
- Dashboard loads in < 3s
- Charts render smoothly
- Report generates in < 10s
- No browser freezing

**Pass/Fail:** [ ]

---

### ✅ Test 15: Data Accuracy

**Steps:**
1. Calculate revenue growth manually
2. Compare with dashboard value
3. Check other metrics

**Expected Result:**
- Calculated values match dashboard
- Formulas correct
- Percentage calculations accurate

**Pass/Fail:** [ ]

---

## Complete Testing Checklist

```
Prerequisites:
[ ] Backend dependencies installed
[ ] Frontend dependencies installed
[ ] Both servers running

Basic Functionality:
[ ] Test 1: Evaluate tab visibility
[ ] Test 2: Dashboard loads
[ ] Test 3: Insight cards display
[ ] Test 4: Revenue trend chart
[ ] Test 5: Expenses vs income chart

Advanced Features:
[ ] Test 6: Additional stats section
[ ] Test 7: Generate IC report
[ ] Test 8: PDF report content
[ ] Test 9: PDF report styling

Quality Assurance:
[ ] Test 10: Responsive design
[ ] Test 11: Error handling
[ ] Test 12: Tab switching
[ ] Test 13: Empty state
[ ] Test 14: Performance
[ ] Test 15: Data accuracy

Documentation:
[ ] All tests documented
[ ] Issues recorded
[ ] Ready for production
```

---

## Expected Results Summary

| Scenario | Expected Time | Expected Result |
|----------|---------------|-----------------|
| Dashboard Load | < 2s | Charts rendered |
| PDF Generation | < 5s | File downloaded |
| Tab Switch | < 1s | Smooth transition |
| Chart Hover | Instant | Tooltip shows |
| Large Dataset | < 3s | Sampled data |

---

## Troubleshooting

### Issue: "Charts not rendering"
**Solution:** Check browser console for errors. Verify Recharts installed.

### Issue: "PDF generation fails"
**Solution:** Ensure ReportLab installed. Check backend logs for errors.

### Issue: "Insight values seem incorrect"
**Solution:** Verify field detection working. Check uploaded data format.

### Issue: "Report download doesn't trigger"
**Solution:** Check browser settings allow downloads. Verify API endpoint.

---

## Success Criteria

**Must Have:**
- ✅ All tests pass
- ✅ No console errors
- ✅ PDF generates correctly
- ✅ Charts render properly

**Nice to Have:**
- ✅ < 2s load time
- ✅ Mobile responsive
- ✅ Professional styling
- ✅ Accurate calculations

---

## Sign-Off

```
Tester: _______________
Date: _______________
Environment: Production / Staging / Dev

All Critical Tests: [ ] Pass [ ] Fail
Critical Issues: _______________

Recommendation: [ ] Ready to Deploy [ ] Needs Fixes
```

---

**Last Updated:** January 2025  
**Next Review:** After deployment


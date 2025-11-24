# Quick Start: Testing Anomalies Feature

**⏱️ Time:** 5 minutes  
**🎯 Goal:** Verify anomalies integration works end-to-end

---

## Step 1: Start Backend (Terminal 1)

```bash
cd FundIQ/Tunnel/backend
python -m uvicorn main:app --reload --port 8000
```

**Expected Output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
✅ Storage initialized: SQLiteStorage
```

---

## Step 2: Start Frontend (Terminal 2)

```bash
cd FundIQ/Tunnel
npm run dev
```

**Expected Output:**
```
Local:   http://localhost:3000
Ready in 2.5s
```

---

## Step 3: Open Browser

Navigate to: **http://localhost:3000**

---

## Step 4: Upload Test File

### Option A: Use Provided Test Data

1. Click "Upload File" button
2. Select: `backend/test_data/revenue_anomalies.csv`
3. Wait for processing (2-5 seconds)
4. Look for green "Success" message

### Option B: Use Custom File

Upload any CSV/Excel file with financial data. Anomalies will auto-detect if patterns exist.

---

## Step 5: View Anomalies

1. Find your uploaded document in the list
2. Click **"View"** or **"Review Data"** button
3. **Click "Anomalies" tab** (third tab)
4. Observe detected issues

**What You Should See:**
- ✅ Table with columns: Severity, Type, Description, Suggested Action, Row, Actions
- ✅ Color-coded badges: 🔴 Red (high), 🟠 Yellow (medium), 🔵 Blue (low)
- ✅ Contextual suggested actions for each anomaly
- ✅ Red badge on tab showing count

---

## Step 6: Test Filtering

1. **Select "High" from Severity dropdown**
   - Should show only red-highlighted anomalies
   
2. **Select "Revenue Anomaly" from Type dropdown**
   - Should filter to revenue-related issues

3. **Click "All" to reset**
   - Shows complete list

---

## Step 7: Test Re-run Detection

1. Click **"Re-run Detection"** button (blue button in header)
2. Watch loading spinner
3. Wait for completion
4. Verify results refresh

---

## ✅ Success Indicators

Check all of these:

- [ ] Backend running without errors
- [ ] Frontend loads without console errors
- [ ] File uploads successfully
- [ ] Anomalies tab visible and clickable
- [ ] Table displays with data
- [ ] Severity badges show correct colors
- [ ] Filters work (severity + type)
- [ ] Re-run detection completes
- [ ] Badge shows correct count

---

## 🐛 Quick Troubleshooting

### "Cannot connect to backend"
- Check backend is running on port 8000
- Try: `curl http://localhost:8000/health`

### "No anomalies detected"
- Upload `backend/test_data/revenue_anomalies.csv` (has known anomalies)
- Check backend logs for processing messages

### "Anomalies tab missing"
- Hard refresh browser (Cmd+Shift+R or Ctrl+Shift+R)
- Check browser console for errors
- Verify all files saved correctly

### "Blank screen"
- Check browser console for errors
- Verify frontend build succeeded
- Try different browser (Chrome/Firefox)

---

## 📸 What Success Looks Like

```
┌─────────────────────────────────────────────────┐
│  FundIQ Document Review                         │
├─────────────────────────────────────────────────┤
│  Table | JSON | Anomalies 🔴3  [Re-run Detection]│
├─────────────────────────────────────────────────┤
│                                                  │
│  Detected Anomalies (3)                         │
│                                                  │
│  Filter: [Severity ▼] [Type ▼]                 │
│                                                  │
│  ┌──────────────────────────────────────────┐  │
│  │ Severity │ Type      │ Description     │  │  │
│  ├──────────────────────────────────────────┤  │
│  │ 🔴 HIGH  │ Revenue   │ Negative rev... │  │  │
│  │ 🟠 MED   │ Expense   │ Missing desc... │  │  │
│  │ 🟢 LOW   │ Payroll   │ Round number... │  │  │
│  └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

---

## 📊 Expected Test Results

Using `revenue_anomalies.csv`:

| Anomaly Type | Count | Severity |
|--------------|-------|----------|
| Revenue Spike | 2 | Medium |
| Revenue Drop | 1 | Medium |
| Negative Revenue | 0-1 | High |

---

## 🎉 You're Done!

If all checks pass, the anomalies feature is working correctly!

**Next Steps:**
- Read full testing guide: `TESTING_GUIDE_ANOMALIES.md`
- Review implementation report: `ANOMALIES_INTEGRATION_REPORT.md`
- Try uploading different file types
- Test with larger datasets

---

**Need Help?**
- Check backend logs: Look for "✅" and "❌" messages
- Check browser console: F12 → Console tab
- Review API calls: F12 → Network tab

---

*Last Updated: January 2025*


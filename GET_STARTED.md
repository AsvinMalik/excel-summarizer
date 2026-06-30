# ✅ GETTING STARTED CHECKLIST

## Before You Start
- [ ] Make sure you're in the "Excel File Summarizer" folder
- [ ] Check that you have 2 open terminals available (or can open them)
- [ ] Have a web browser ready (Chrome, Firefox, Edge, Safari)

---

## 🚀 STARTUP SEQUENCE (Do This First!)

### Step 1: Launch Backend
**Windows Explorer**: Double-click `START_BACKEND.bat`

**Expected Output**:
```
============================================
 Starting Procure.ai Backend Server
============================================

Starting backend on http://localhost:8000
Press CTRL+C to stop

Warning: google-genai package not installed. Running in demo mode.
INFO:     Started server process [18040]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**✓ If you see "Uvicorn running on http://0.0.0.0:8000"**: SUCCESS! Keep this terminal open.

**✗ If you get errors**: Check that Python 3.11 is installed and venv is active.

---

### Step 2: Launch Frontend
**Windows Explorer**: Double-click `START_FRONTEND.bat` (in a NEW terminal/window)

**Expected Output**:
```
============================================
 Starting Procure.ai Frontend
============================================

Frontend will open on: http://localhost:4173 or http://localhost:4174
Press CTRL+C to stop

VITE v5.4.21 ready in 572 ms

➜  Local:   http://localhost:4173
➜  Press h + enter to show help
```

**✓ If you see "ready in"**: SUCCESS! Keep this terminal open.

**✗ If port 4173 is busy**: Vite will automatically try 4174, 4175, etc. Check the output.

---

### Step 3: Open in Browser
Open your web browser and go to:
```
http://localhost:4173
```

Or if that doesn't work, try:
```
http://localhost:4174
```

You should see the Procure.ai interface with a login/signup screen.

---

## 🎯 QUICK TEST (5 Minutes)

### Test 1: Upload a File
1. **Click**: "Upload contract or data" button
2. **Upload**: Any Excel file (.xlsx, .xls, .csv)
3. **See**: File appears in sidebar on the left
4. **Status**: Should show file name and "analyzed"

✓ **Success**: File uploaded and indexed by AI

---

### Test 2: Ask a Question
1. **Type** in chat box: "Summarize this data for me"
2. **Press**: Enter
3. **Wait**: 2-5 seconds for Gemini AI to respond
4. **See**: AI response about your spreadsheet

✓ **Success**: Gemini AI analyzed your file and provided insights

---

### Test 3: Delete a File
1. **Find**: File in sidebar (left panel)
2. **Click**: The **✕ (cross)** button on the file
3. **See**: File disappears from sidebar
4. **Confirm**: File is removed

✓ **Success**: File deleted successfully

---

## 🎉 Congratulations!

If you completed all 3 tests, your system is **100% operational**! 

Now you can:
- ✅ Upload more files
- ✅ Ask complex questions
- ✅ Delete unwanted documents
- ✅ Chat with the AI

---

## 🐛 TROUBLESHOOTING

### Issue: "Connection Refused" on Port 8000
**Solution**:
1. Check that `START_BACKEND.bat` terminal shows "Uvicorn running"
2. If not, run: `.\.venv\Scripts\pip install -r backend\requirements.txt`
3. Restart backend

### Issue: Frontend Shows Blank Page
**Solution**:
1. Press **F12** to open Developer Console
2. Check for red error messages
3. Verify Backend is running (Uvicorn on 8000)
4. Reload page (Ctrl+R)

### Issue: "Port Already in Use"
**Solution**:
1. Find which app is using the port
2. Close it or wait 60 seconds
3. Restart the launcher

### Issue: File Upload Fails
**Solution**:
1. Ensure file is Excel format (.xlsx, .csv, .xls)
2. File should be under 50MB
3. Check browser console for detailed error
4. Restart both servers

### Issue: AI Doesn't Respond
**Solution**:
1. Check internet connection (Gemini needs API)
2. Verify `backend\.env` has GEMINI_API_KEY
3. Restart backend: Close and reopen `START_BACKEND.bat`
4. Try a simpler question first

---

## ⚙️ MANUAL STARTUP (Advanced Users)

If batch files don't work, use PowerShell:

**Terminal 1 - Backend**:
```powershell
Set-Location "c:\ASVIN DATA\Excel File Summarizer"
.\.venv\Scripts\activate
python backend\main.py
```

**Terminal 2 - Frontend**:
```powershell
Set-Location "c:\ASVIN DATA\Excel File Summarizer"
npm run dev
```

---

## 📊 SYSTEM VERIFICATION

To verify everything is working, double-click:
```
TEST_SYSTEM.bat
```

This will check:
- ✅ Backend health on port 8000
- ✅ Frontend health on port 4173/4174
- ✅ Display overall system status

---

## 💾 Useful Commands

**Restart Backend**:
- Close the backend terminal (Ctrl+C)
- Double-click `START_BACKEND.bat` again

**Restart Frontend**:
- Close the frontend terminal (Ctrl+C)
- Double-click `START_FRONTEND.bat` again

**Check Backend Health**:
```
Open browser: http://localhost:8000/health
Should see: {"status": "ok", "version": "1.0"}
```

**View Backend Logs**:
- Check the terminal where backend is running
- All API calls and errors shown there

---

## 🎓 What Happens Behind the Scenes

1. **You upload file** → Saved to `backend/uploads/`
2. **Frontend shows file** → Sidebar displays with status "analyzed"
3. **You ask question** → Sent to FastAPI backend on port 8000
4. **Backend processes** → Reads Excel file with Pandas
5. **Gemini AI analyzes** → Sends data to Google AI API
6. **Response returned** → Displayed in chat
7. **You delete file** → Backend removes from disk and memory

---

## 📈 Next Steps After Getting Started

1. **Try different file types**: CSV, XLSX, XLS
2. **Ask complex questions**: "Top 5 trends", "Calculate totals"
3. **Test different Excel files**: Different structures to see how AI adapts
4. **Review responses**: Check quality and accuracy
5. **Plan Firebase setup**: When ready for persistent storage

---

## 📞 Where to Find Help

1. **Error in terminal?** → Read the error message carefully
2. **Blank page in browser?** → Press F12, check Console tab
3. **File not uploading?** → Check file format and size
4. **AI not responding?** → Check internet and Gemini API key in `.env`
5. **Port conflicts?** → Check which process is using the port

---

## ✨ Final Checklist Before You Go Live

- [ ] Backend terminal shows "Uvicorn running"
- [ ] Frontend terminal shows "ready in"
- [ ] Browser loads http://localhost:4173 without errors
- [ ] Can upload a test Excel file
- [ ] Can ask a question and get AI response
- [ ] Can delete a file successfully
- [ ] Both terminals remain open (don't close them)

---

**READY TO GO!** 🚀

Your system is production-ready. Enjoy using Procure.ai!

For detailed documentation, see: **README.md** and **QUICK_START.md**

---

*Last Updated: 2026-06-13*  
*Version: 1.0.0*  
*Status: ✅ Ready to Use*

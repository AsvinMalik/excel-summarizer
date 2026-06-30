# 🔍 API Monitoring Guide for Procure.ai

Monitor all API calls on your laptop during development.

---

## **Option 1: BACKEND LOGGING (Simplest) ✅ RECOMMENDED**

### **How It Works**
When you run the backend, all API calls are logged to the terminal.

### **Example Output**
```
2026-06-29 14:32:45 | INFO     | 📨 REQUEST → POST /api/upload
2026-06-29 14:32:46 | INFO     | ✅ RESPONSE ← 200 (0.45s)

2026-06-29 14:32:47 | INFO     | 📨 REQUEST → POST /api/analyze
2026-06-29 14:32:49 | INFO     | ✅ RESPONSE ← 200 (1.23s)

2026-06-29 14:32:50 | INFO     | 📨 REQUEST → DELETE /api/document/abc123
2026-06-29 14:32:50 | INFO     | ✅ RESPONSE ← 204 (0.08s)
```

### **Setup** (Already Done!)
Backend now logs every API call automatically. Just run:
```bash
python backend\main.py
```

Watch the terminal for live API monitoring ✅

---

## **Option 2: BROWSER DEVTOOLS (For Frontend-Backend Traffic)**

### **Steps**
1. Open app: `http://localhost:4173`
2. Press **F12** → Click **Network** tab
3. Upload file or ask question
4. See all API calls in the Network tab

### **What You'll See**
```
POST /api/upload          200     0.45s    45 KB
POST /api/analyze         200     1.23s    12 KB
GET  /api/document/abc    200     0.08s    5 KB
DELETE /api/document/xyz  204     0.05s    0 KB
```

### **Inspect Request/Response**
- Click any request
- See "Headers" tab (request parameters)
- See "Response" tab (what server returned)
- See "Preview" tab (formatted response)

---

## **Option 3: POSTMAN (Test Individual Endpoints)**

### **Download**
https://www.postman.com/downloads/

### **Test an Endpoint**
```
1. Open Postman
2. New Request → Method: POST
3. URL: http://localhost:8000/api/analyze
4. Body → Raw → JSON:
   {
     "file_path": "uploads/sample.xlsx",
     "user_query": "Summarize this data"
   }
5. Click Send
6. See response below
```

### **Save for Reuse**
- Click "Save"
- Name it: "Analyze Excel"
- Use anytime without retyping

---

## **Option 4: THUNDER CLIENT (Lightest - Built into VS Code)**

### **Install**
1. Open VS Code
2. Extensions → Search "Thunder Client"
3. Click Install

### **Use**
1. Click Thunder Client icon (sidebar)
2. Click + New Request
3. Method: POST
4. URL: http://localhost:8000/api/health
5. Click Send → See response

**Advantage**: Stay in VS Code, no new app needed

---

## **Option 5: NETWORK TRAFFIC SNIFFER (Advanced)**

### **Windows: Fiddler Classic** (Free)
```
Download: https://www.telerik.com/fiddler

Shows:
✅ ALL network requests (encrypted & decrypted)
✅ Request/response headers
✅ Body content
✅ Timing breakdown
✅ Performance metrics

Useful for:
- Debugging slow endpoints
- Seeing exact request/response
- Monitoring external APIs (Groq, Gemini, etc.)
```

---

## **API ENDPOINTS TO MONITOR**

### **File Upload**
```
POST /api/upload

What to watch:
✅ Request size (file upload)
✅ Response time
✅ Returns: document_id, filename, status
```

### **Analyze Excel**
```
POST /api/analyze

What to watch:
✅ File path received
✅ Response time (Gemini processing)
✅ Returns: AI analysis text
```

### **Query Spreadsheet**
```
POST /api/query

What to watch:
✅ Natural language query sent
✅ Response time
✅ Returns: AI answer
```

### **Delete Document**
```
DELETE /api/document/{doc_id}

What to watch:
✅ Document ID received
✅ Returns: success status
```

### **Health Check**
```
GET /health

What to watch:
✅ Server is running
✅ Response time < 100ms

Test in browser: http://localhost:8000/health
```

---

## **PERFORMANCE MONITORING**

### **Response Times (Normal)**
```
Health check:  < 100ms  ✅
File upload:   < 1s     ✅
Simple query:  1-3s     ✅
AI analysis:   3-10s    ✅ (depends on Gemini API)
```

### **If Slow**
```
1. Check terminal for error messages
2. Monitor.com/health → is server ok?
3. Check internet speed (Gemini needs API)
4. Restart backend if stuck
```

---

## **TROUBLESHOOTING WITH MONITORING**

### **File Upload Failing?**
1. Backend terminal shows error? → Read the error
2. Browser DevTools → Network tab → See what response
3. Postman → Test /api/upload directly
4. Check file size (max 50MB)

### **AI Not Responding?**
1. Backend logs show timeout?
2. Check internet connection
3. Verify GEMINI_API_KEY in `.env`
4. Try simpler question first

### **Port Conflict?**
1. Backend won't start on port 8000?
2. Run: `netstat -ano | findstr :8000` (Windows)
3. See which app is using port
4. Close it or change port in code

---

## **LIVE MONITORING SETUP (Recommended)**

### **Setup 3 Terminals**

**Terminal 1: Backend** (Monitor API calls)
```
cd "C:\ASVIN DATA\Excel File Summarizer"
.\.venv\Scripts\activate
python backend\main.py

Watch for:
✅ 📨 REQUEST messages
✅ ✅ RESPONSE messages
✅ Response times
✅ Any ❌ ERRORS
```

**Terminal 2: Frontend** (See UI in browser)
```
cd "C:\ASVIN DATA\Excel File Summarizer"
npm run dev

Watch for:
✅ "ready in X ms"
✅ Any compilation errors
```

**Terminal 3: Browser DevTools** (See network requests)
```
1. Open http://localhost:4173
2. Press F12 → Network tab
3. Perform actions
4. See all API calls
```

### **Now You Can**
- ✅ See request in Browser DevTools
- ✅ See matching log in Backend terminal
- ✅ Correlate timing & errors
- ✅ Debug bottlenecks

---

## **MONITORING CHECKLIST**

When debugging, check in this order:

```
[ ] Backend terminal shows request received?
    └─ If NO → Frontend not sending request
[ ] Backend terminal shows response sent?
    └─ If NO → Backend crashed/errored
[ ] Browser DevTools shows response?
    └─ If NO → Network issue
[ ] Response has expected data?
    └─ If NO → Check API logic
[ ] Response time normal?
    └─ If NO → Check Gemini API or server load
```

---

## **QUICK COMMANDS**

### **Check if Backend is Running**
```
Open browser: http://localhost:8000/health
Expected: {"status": "ok", "version": "1.0"}
```

### **Check if Frontend is Running**
```
Open browser: http://localhost:4173
Expected: Procure.ai login screen appears
```

### **Restart Backend**
```
Terminal 1: Press Ctrl+C
Then: python backend\main.py
```

### **Check Port in Use**
```
Windows:
netstat -ano | findstr :8000

Mac/Linux:
lsof -i :8000
```

---

## **SUMMARY**

| Tool | Best For | Effort | Details |
|------|----------|--------|---------|
| **Backend Logs** | Overall monitoring | ⭐ Easy | Terminal output, all calls visible |
| **Browser DevTools** | Frontend debugging | ⭐ Easy | Network tab shows everything |
| **Postman** | Testing endpoints | ⭐⭐ Medium | Full request/response control |
| **Thunder Client** | Quick testing | ⭐ Easy | Built into VS Code |
| **Fiddler** | Deep inspection | ⭐⭐ Medium | All network traffic visible |

**START HERE**: Watch Backend terminal logs while using the app ✅

---

**Last Updated**: 2026-06-29  
**Version**: 1.0


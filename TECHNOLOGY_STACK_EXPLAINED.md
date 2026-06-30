# 🛠️ Technology Stack - Complete Explanation

All technologies used in Procure.ai and their roles.

---

## **📊 System Architecture Overview**

```
┌─────────────────────────────────────────────────────────┐
│                    USER BROWSER                         │
│  (React + Vite + Tailwind CSS)                          │
│  - Upload files                                         │
│  - Chat interface                                       │
│  - Authentication                                       │
└────────────────┬────────────────────────────────────────┘
                 │ HTTP/REST
┌────────────────▼────────────────────────────────────────┐
│              BACKEND SERVER                             │
│  (FastAPI + Uvicorn)                                    │
│  - File processing                                      │
│  - API orchestration                                    │
│  - Fallback chain logic                                 │
└────────────────┬────────────────────────────────────────┘
                 │
    ┌────────────┼────────────┬────────────┐
    │            │            │            │
    ▼            ▼            ▼            ▼
 GROQ API   OLLAMA LOCAL   CEREBRAS API   FIREBASE
 (Primary)  (Unlimited)    (Fallback)     (Auth/DB)
```

---

## **FRONTEND TECHNOLOGIES**

### **1. React 18.3** 🎨
**What it is:** JavaScript library for building user interfaces

**Role in Procure.ai:**
- Build interactive UI components
- Manage UI state (chat messages, uploaded files, etc.)
- Handle user interactions (click, type, upload)
- Real-time updates without page reload

**Example:**
```jsx
// Upload file component
<ProcurementAssistant />
  ├─ FileUploader.jsx (drag-drop interface)
  ├─ ChatPanel.jsx (conversation display)
  └─ DocumentList.jsx (sidebar file list)
```

**Why Use React?**
- Fast & responsive (virtual DOM)
- Component reusability
- Large ecosystem & community
- Easy to manage complex UIs

---

### **2. Vite 5.4** ⚡
**What it is:** Frontend build tool (faster than Webpack)

**Role in Procure.ai:**
- Bundle React code for browser
- Hot module replacement (HMR) - instant updates while coding
- Optimize production build
- Serve frontend on port 4173

**Example:**
```bash
npm run dev    # Start dev server on localhost:4173
npm run build  # Create optimized production build
```

**Why Use Vite?**
- 10x faster than Webpack
- Instant reload during development
- Smaller bundle size
- Modern ES modules support

---

### **3. Tailwind CSS 3.4** 🎨
**What it is:** Utility-first CSS framework

**Role in Procure.ai:**
- Style all UI components
- Responsive design (mobile/tablet/desktop)
- Dark/light mode support
- Consistent design system

**Example:**
```html
<!-- Login button styling -->
<button class="bg-blue-600 hover:bg-blue-700 text-white 
                px-4 py-2 rounded-lg">
  Login
</button>
```

**Why Use Tailwind?**
- Write CSS in HTML (no separate files)
- Pre-built component styles
- Responsive out of box
- Easy theme customization

---

### **4. Firebase SDK 10.11** 🔐
**What it is:** Google's backend-as-a-service platform

**Role in Procure.ai:**
- User authentication (email/password, Google OAuth)
- User session management
- Store user data (Firestore database)
- Optional but recommended for production

**Example:**
```javascript
// Sign up user
firebase.auth().createUserWithEmailAndPassword(email, password)
  .then(user => console.log("User created:", user))
```

**Why Use Firebase?**
- No server setup needed
- Secure authentication
- Real-time database (Firestore)
- Easy to scale

---

## **BACKEND TECHNOLOGIES**

### **5. FastAPI 0.136** 🚀
**What it is:** Modern Python web framework (fastest available)

**Role in Procure.ai:**
- Create REST API endpoints (/api/upload, /api/analyze, etc.)
- Handle HTTP requests from frontend
- Orchestrate AI models & fallback chains
- Validate request data (Pydantic models)

**Example:**
```python
@app.post("/api/analyze")
async def analyze(file_path: str, user_query: str):
    # Analyze Excel with AI
    result = await procure_agent(file_path, user_query)
    return result
```

**API Endpoints:**
```
POST   /api/upload              → Upload files
POST   /api/analyze             → Analyze with AI
POST   /api/query               → Ask questions
DELETE /api/document/{doc_id}   → Delete file
GET    /health                  → Server status
```

**Why Use FastAPI?**
- Fastest Python framework (auto-optimized)
- Built-in API documentation (Swagger UI)
- Automatic request validation
- Async/await support for speed
- Type hints for safety

---

### **6. Uvicorn 0.49** ⚙️
**What it is:** ASGI web server (runs FastAPI)

**Role in Procure.ai:**
- Host the backend server
- Listen on port 8000
- Handle concurrent requests
- Pass requests to FastAPI

**Example:**
```bash
python backend/main.py
# Starts Uvicorn on http://localhost:8000
```

**Why Use Uvicorn?**
- Extremely fast (C-based)
- Handles thousands of concurrent requests
- Standards-compliant (ASGI)
- Production-ready

---

### **7. Pydantic** 📋
**What it is:** Data validation library

**Role in Procure.ai:**
- Validate incoming API requests
- Ensure data types are correct
- Auto-generate API documentation
- Prevent bad data from entering system

**Example:**
```python
class DocumentUpload(BaseModel):
    file_name: str
    doc_type: str  # "contract" or "spreadsheet"
    company_name: str
    user_id: str

# FastAPI automatically validates:
# - All fields present
# - Correct data types
# - Returns error if invalid
```

**Why Use Pydantic?**
- Prevents crashes from bad data
- Clear error messages
- Type-safe code

---

## **DATA PROCESSING TECHNOLOGIES**

### **8. Pandas 3.0** 📊
**What it is:** Data analysis & manipulation library

**Role in Procure.ai:**
- Read Excel files (.xlsx, .xls, .csv)
- Extract data from spreadsheets
- Clean & transform data
- Pass to AI for analysis

**Example:**
```python
import pandas as pd

# Read uploaded Excel file
df = pd.read_excel("vendors.xlsx")

# Get columns
columns = df.columns.tolist()

# Filter data
top_vendors = df.nlargest(5, "spend")

# Convert to text for AI
text = df.to_string()
```

**Why Use Pandas?**
- Industry standard for data analysis
- Fast & efficient
- Works with all data formats
- Easy filtering/grouping

---

### **9. OpenPyXL 3.1** 📋
**What it is:** Library for reading/writing Excel files

**Role in Procure.ai:**
- Read Excel formula, formatting, metadata
- Preserve cell styles & structure
- Handle complex Excel files
- Work alongside Pandas for detailed parsing

**Example:**
```python
from openpyxl import load_workbook

wb = load_workbook("contracts.xlsx")
ws = wb.active

# Read cell values with formulas
for row in ws.iter_rows():
    for cell in row:
        print(cell.value)
```

**Why Use OpenPyXL?**
- Preserves Excel formatting
- Access to formulas & metadata
- More control than Pandas alone
- Handles complex sheets

---

## **AI/LLM TECHNOLOGIES (Fallback Chain)**

### **FALLBACK TIER 1: Groq API** 🔵 PRIMARY

**What it is:** Fast LLM inference service (free tier)

**Role in Procure.ai:**
- Primary AI provider
- Fast responses (0.5-1 second)
- 7,000 requests per day (free)
- 90% quality (Llama 3.3 70B model)

**Setup:**
```python
from groq import Groq

client = Groq(api_key="gsk_...")
response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": query}]
)
```

**Free Tier Details:**
- 7,000 requests/day
- Resets midnight UTC
- Ultra-fast responses
- Best for production

**Use in Demo:**
```
✅ If available: Use Groq (fastest)
❌ If exhausted: Fall back to Ollama
```

---

### **FALLBACK TIER 2: Ollama (Self-Hosted)** 🟢 UNLIMITED

**What it is:** Local AI model runtime (runs on your GPU)

**Role in Procure.ai:**
- Unlimited responses (no API quota)
- 100% private (no data sent to cloud)
- Runs on RTX 5060 GPU locally
- Slower but free & unlimited

**Models Available:**
```bash
ollama pull phi3        # 4.7GB, 75% quality
ollama pull mistral     # 5.4GB, 85% quality
ollama serve            # Start service on localhost:11434
```

**Setup in Backend:**
```python
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "phi3"  # or "mistral"

response = requests.post(
    f"{OLLAMA_URL}/api/generate",
    json={"model": OLLAMA_MODEL, "prompt": query}
)
```

**Why Use Ollama?**
- Unlimited (no quota)
- Private (data stays local)
- Free (just electricity cost)
- Backup when APIs fail

**Your Hardware:**
- GPU: RTX 5060 (8GB VRAM)
- CPU: Ryzen 7 250 (24GB RAM)
- Can run Phi3 + Mistral simultaneously

---

### **FALLBACK TIER 3: Cerebras API** 🟡 BACKUP

**What it is:** Fast LLM service (free tier)

**Role in Procure.ai:**
- Secondary fallback
- 1 million tokens per day (free)
- Very fast inference (1-2 seconds)
- 90% quality (Llama 3.1 70B)

**Setup:**
```python
from cerebras_cloud_sdk import Cerebras

client = Cerebras(api_key="csk_...")
response = client.messages.create(
    model="llama3.1-70b",
    messages=[{"role": "user", "content": query}]
)
```

**When to Use:**
- Groq quota exhausted
- Ollama offline
- Need ultra-fast response

---

### **FALLBACK TIER 4: OpenRouter** 🟡 EXTRA BACKUP

**What it is:** API aggregator (multiple model access)

**Role in Procure.ai:**
- Additional fallback layer
- Free-tier OpenAI model available
- Access to multiple providers
- Extra safety net

**Setup:**
```python
response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
    json={
        "model": "openai/gpt-oss-20b:free",
        "messages": [{"role": "user", "content": query}]
    }
)
```

---

### **FALLBACK TIER 5: Demo Mode** ⚪ LAST RESORT

**What it is:** Hardcoded template responses

**Role in Procure.ai:**
- Ultimate fallback if all APIs fail
- Shows working UI even offline
- For demo/testing purposes
- No API calls needed

**Example Response:**
```python
return {
    "analysis": "Demo mode - All APIs unavailable. "
                "Sample analysis: File contains 100 rows "
                "of vendor data with pricing information.",
    "status": "demo_mode"
}
```

---

## **FALLBACK CHAIN LOGIC**

```
User asks question
    ↓
Try GROQ API
    ├─ Success? → Return response ✅
    └─ Fail? ↓
Try OLLAMA Local (http://localhost:11434)
    ├─ Success? → Return response ✅
    └─ Fail? ↓
Try CEREBRAS API
    ├─ Success? → Return response ✅
    └─ Fail? ↓
Try OPENROUTER API
    ├─ Success? → Return response ✅
    └─ Fail? ↓
Use DEMO MODE
    └─ Return template response ✅
```

**Code Implementation:**
```python
async def procure_agent(query: str, file_path: str):
    """Try each provider in order"""
    
    # Tier 1: Groq
    try:
        return await groq_provider.analyze(query, file_path)
    except:
        logger.info("Groq failed, trying Ollama...")
    
    # Tier 2: Ollama
    try:
        return await phi3_provider.analyze(query, file_path)
    except:
        logger.info("Ollama failed, trying Cerebras...")
    
    # Tier 3: Cerebras
    try:
        return await cerebras_provider.analyze(query, file_path)
    except:
        logger.info("Cerebras failed, trying OpenRouter...")
    
    # Tier 4: OpenRouter
    try:
        return await openrouter_provider.analyze(query, file_path)
    except:
        logger.info("All APIs failed, using demo mode...")
    
    # Tier 5: Demo Mode
    return demo_provider.get_sample_response()
```

---

## **UTILITY LIBRARIES**

### **10. python-dotenv**
**What it is:** Load environment variables from .env file

**Role:**
```python
from dotenv import load_dotenv
import os

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
```

**Why:** Secure credential management (don't hardcode API keys)

---

### **11. Requests**
**What it is:** HTTP client library

**Role:**
```python
import requests

response = requests.post(
    "http://localhost:11434/api/generate",
    json={"model": "phi3", "prompt": "..."}
)
```

**Why:** Make HTTP calls to APIs & Ollama

---

### **12. Starlette** 
**What it is:** Web framework (FastAPI is built on it)

**Role:**
- Handle CORS (cross-origin requests)
- Middleware support
- Request/response handling

---

## **📁 How Technologies Work Together**

### **1. User Uploads Excel File**

```
User (Browser)
    ↓ Click "Upload"
React Component
    ↓ Reads file from disk
Frontend JavaScript
    ↓ POST request to /api/upload
HTTP (REST)
    ↓
FastAPI Backend (Port 8000)
    ↓ Receives upload
File Handler
    ↓ Save to disk
Store in DOCUMENT_STORE
```

---

### **2. User Asks Question**

```
User (Browser)
    ↓ Type question & press Enter
React Chat Component
    ↓ Create message object
Frontend JavaScript
    ↓ POST to /api/analyze
HTTP Request
    ↓
FastAPI Backend
    ↓ Receive query
Pandas
    ↓ Read Excel file
Extract data → Convert to text
    ↓
Procure Agent (Fallback Chain)
    ├─ Try Groq API
    ├─ Try Ollama (localhost:11434)
    ├─ Try Cerebras API
    ├─ Try OpenRouter
    └─ Use Demo Mode
    ↓
Get AI Response
    ↓
HTTP Response (JSON)
    ↓
Frontend JavaScript
    ↓ Parse response
React Component
    ↓ Display in chat
User (Browser)
    ↓ Sees answer
```

---

### **3. User Logs In (Optional - Firebase)**

```
User (Browser)
    ↓ Email + Password
React Auth Component
    ↓
Firebase SDK
    ↓ Send to Google servers
Firebase Auth
    ↓ Validate credentials
Create User Session
    ↓ Return token
Frontend JavaScript
    ↓ Store token locally
React State
    ↓ Update UI (show dashboard)
User (Browser)
    ↓ Logged in ✅
```

---

## **DEPLOYMENT TARGETS**

### **Development (Your Laptop - Now)**
```
Frontend: http://localhost:4173 (Vite dev server)
Backend:  http://localhost:8000 (Uvicorn)
Ollama:   http://localhost:11434 (Local GPU)
```

### **Production (Company Server - Optional)**
```
Frontend: Deployed to Vercel/Netlify
Backend:  Deployed to AWS/Railway/Render
Ollama:   On GPU cluster
Firebase: Google servers
Database: Firestore (Google)
```

---

## **TECHNOLOGY COMPARISON TABLE**

| Layer | Technology | Role | Speed | Cost |
|-------|-----------|------|-------|------|
| **Frontend UI** | React + Vite | User interface | Fast | Free |
| **Frontend Styling** | Tailwind CSS | Design system | N/A | Free |
| **Frontend Auth** | Firebase SDK | User login | Fast | Free tier |
| **Backend Server** | FastAPI | API endpoints | 10ms | Free |
| **Backend Runtime** | Uvicorn | Host server | Fast | Free |
| **Data Validation** | Pydantic | Input safety | N/A | Free |
| **Excel Reading** | Pandas + OpenPyXL | Data extraction | Fast | Free |
| **AI Primary** | Groq API | Analyze data | 0.5-1s | Free (7K/day) |
| **AI Fallback 1** | Ollama Local | Backup AI | 5-10s | Free (unlimited) |
| **AI Fallback 2** | Cerebras API | Secondary | 1-2s | Free (1M tokens/day) |
| **AI Fallback 3** | OpenRouter | Extra backup | Varies | Free tier |
| **Database** | Firestore | User data | Fast | Free tier |

---

## **COST BREAKDOWN (Monthly)**

```
DEVELOPMENT (Your Laptop - Now):
├─ Groq API:     Free (7K requests/day)
├─ Cerebras API: Free (1M tokens/day)
├─ Ollama:       Free + electricity (~₹100-500)
├─ Firebase:     Free tier
└─ Total:        ₹500-1,000/month ✅ CHEAPEST

PRODUCTION (Company):
├─ Groq API:     ₹2-10 Lakhs/month
├─ Ollama:       ₹3-20 Lakhs/month (infra)
├─ Firebase:     ₹1-5 Lakhs/month
├─ Servers:      ₹5-50 Lakhs/month
└─ Total:        ₹11-85 Lakhs/month (scales with usage)
```

---

## **WHEN TO USE EACH TECHNOLOGY**

### **During Development**
```
✅ React: Build UI features
✅ FastAPI: Create API endpoints
✅ Pandas: Parse Excel files
✅ Ollama: Test AI without quota limits
✅ Firebase: Optional for auth testing
```

### **For Your Demo Tomorrow**
```
✅ Use Groq (fast, fresh quota at midnight)
✅ Fallback to Ollama (unlimited)
✅ Show all endpoints working
✅ Monitor with DevTools (Network tab)
```

### **For Production**
```
✅ All technologies above
✅ Add Redis (caching)
✅ Add PostgreSQL (production DB)
✅ Add Docker (containerization)
✅ Add Kubernetes (scaling)
✅ Add LoadBalancer (traffic distribution)
```

---

## **QUICK TECH GLOSSARY**

| Term | Means | Example |
|------|-------|---------|
| **API** | Interface for apps to talk | POST /api/analyze |
| **REST** | Standard API design | HTTP GET, POST, DELETE |
| **JSON** | Data format | `{"name": "John", "age": 30}` |
| **Async** | Non-blocking operations | `await response` |
| **SDK** | Code library for service | Firebase SDK |
| **CORS** | Allow cross-site requests | localhost:4173 → localhost:8000 |
| **Token** | API credential | `gsk_abc123...` |
| **Quota** | API usage limit | 7,000 requests/day |
| **Fallback** | Backup plan | Try Ollama if Groq fails |
| **Middleware** | Intercept requests | CORS, logging |

---

## **SUMMARY**

```
Procure.ai uses 12 core technologies:

FRONTEND (3):
  ✓ React - UI framework
  ✓ Vite - Build tool
  ✓ Tailwind - Styling

BACKEND (5):
  ✓ FastAPI - Web framework
  ✓ Uvicorn - Server
  ✓ Pydantic - Validation
  ✓ Pandas - Data analysis
  ✓ OpenPyXL - Excel reading

AI/LLMs (5):
  ✓ Groq - Primary AI (fastest)
  ✓ Ollama - Local AI (unlimited)
  ✓ Cerebras - Backup AI
  ✓ OpenRouter - Extra backup
  ✓ Demo Mode - Fallback

UTILITIES (2):
  ✓ python-dotenv - Config
  ✓ requests - HTTP client

INFRASTRUCTURE (1):
  ✓ Firebase - Auth + DB (optional)
```

---

**Last Updated**: 2026-06-30  
**Version**: 1.0  
**Status**: All technologies explained ✅


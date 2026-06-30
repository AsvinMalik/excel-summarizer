PROCURE.AI INTEGRATION GUIDE

================================================================================
1. API INTEGRATION WITH CLAUDE / EXTERNAL LLM
================================================================================

Using the System Prompt with Claude API:

```python
import anthropic
import json
from datetime import datetime

client = anthropic.Anthropic(api_key="sk-xxx")

SYSTEM_PROMPT = """
[Full Procure.ai system prompt here - see agent_system_prompt.txt]
"""

def procure_agent(user_query: str, document_context: dict = None, session_state: dict = None):
    """
    Main agent function. Handles user queries with multi-turn conversation.
    
    Args:
        user_query: User's natural language request
        document_context: Active documents (e.g., { "Acme_MSA": {...}, ... })
        session_state: Conversation history and preferences
    
    Returns:
        Structured response with answer, tool calls, and metadata
    """
    
    # Build conversation messages
    messages = []
    
    # Add session history if available
    if session_state and "conversation_history" in session_state:
        for turn in session_state["conversation_history"][-10:]:  # Last 10 turns
            messages.append({
                "role": turn["role"],
                "content": turn["content"]
            })
    
    # Add current user query
    messages.append({
        "role": "user",
        "content": user_query
    })
    
    # Build context injection (active documents)
    context_block = ""
    if document_context:
        context_block = "\n\n[ACTIVE DOCUMENTS IN SESSION]\n"
        for doc_name, doc_data in document_context.items():
            context_block += f"- {doc_name}: {doc_data.get('summary', 'N/A')[:200]}...\n"
        
        # Inject context into system prompt
        system_with_context = SYSTEM_PROMPT + context_block
    else:
        system_with_context = SYSTEM_PROMPT
    
    # Call Claude API
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=system_with_context,
        messages=messages,
        tools=[
            {
                "name": "process_contract",
                "description": "Extract summary, clauses, risks from uploaded contract",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string", "description": "Document identifier"},
                        "extraction_type": {
                            "type": "string",
                            "enum": ["summary", "clauses", "entities"],
                            "description": "Type of extraction"
                        }
                    },
                    "required": ["doc_id", "extraction_type"]
                }
            },
            {
                "name": "execute_query",
                "description": "Run SQL query against vendor spreadsheet",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {"type": "string"},
                        "query": {"type": "string", "description": "SQL SELECT query"}
                    },
                    "required": ["spreadsheet_id", "query"]
                }
            },
            {
                "name": "semantic_search",
                "description": "Search contracts using vector similarity",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (e.g., 'termination clauses')"},
                        "doc_ids": {"type": "array", "items": {"type": "string"}},
                        "top_k": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "generate_report",
                "description": "Create formatted report (vendor, spend, risk, or activity)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "report_type": {
                            "type": "string",
                            "enum": ["vendor_summary", "spend", "risk", "activity"],
                            "description": "Type of report"
                        },
                        "filters": {"type": "object", "description": "Filter criteria"}
                    },
                    "required": ["report_type"]
                }
            },
            {
                "name": "export_to_docx",
                "description": "Convert analysis to downloadable DOCX file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "object", "description": "Content to export"},
                        "format": {"type": "string", "enum": ["standard", "executive"]}
                    },
                    "required": ["content"]
                }
            }
        ]
    )
    
    # Process response
    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "model": "claude-opus-4-6",
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens
        },
        "content": [],
        "tool_calls": []
    }
    
    for block in response.content:
        if block.type == "text":
            output["content"].append({
                "type": "text",
                "text": block.text
            })
        elif block.type == "tool_use":
            output["tool_calls"].append({
                "tool_name": block.name,
                "tool_id": block.id,
                "input": block.input
            })
    
    return output


def handle_tool_execution(tool_name: str, tool_input: dict) -> dict:
    """
    Execute tool calls and return results for agent to process.
    This runs in a sandbox to prevent side effects.
    """
    
    if tool_name == "process_contract":
        # Call document processing backend
        from document_service import extract_contract_intelligence
        result = extract_contract_intelligence(
            doc_id=tool_input["doc_id"],
            extraction_type=tool_input["extraction_type"]
        )
        return result
    
    elif tool_name == "execute_query":
        # Run SQL query in sandbox
        from database_service import execute_query_safe
        result = execute_query_safe(
            spreadsheet_id=tool_input["spreadsheet_id"],
            query=tool_input["query"],
            timeout=30  # 30 second timeout
        )
        return result
    
    elif tool_name == "semantic_search":
        # RAG vector search
        from rag_service import semantic_search
        result = semantic_search(
            query=tool_input["query"],
            doc_ids=tool_input.get("doc_ids", []),
            top_k=tool_input.get("top_k", 5)
        )
        return result
    
    elif tool_name == "generate_report":
        # Report templating
        from report_service import generate_report
        result = generate_report(
            report_type=tool_input["report_type"],
            filters=tool_input.get("filters", {})
        )
        return result
    
    elif tool_name == "export_to_docx":
        # DOCX generation
        from export_service import export_to_docx
        result = export_to_docx(
            content=tool_input["content"],
            format=tool_input.get("format", "standard")
        )
        return result
    
    else:
        return {"error": f"Unknown tool: {tool_name}"}


def agentic_loop(user_query: str, document_context: dict = None, session_state: dict = None, max_iterations: int = 5):
    """
    Run agentic loop: agent calls tools, processes results, continues until done.
    """
    
    iteration = 0
    final_response = None
    
    while iteration < max_iterations:
        iteration += 1
        
        # Get agent response
        response = procure_agent(user_query, document_context, session_state)
        
        # Check if agent produced final text (no tool calls) or produced tool calls
        has_text = any(block["type"] == "text" for block in response["content"])
        has_tools = len(response["tool_calls"]) > 0
        
        if has_text and not has_tools:
            # Agent produced final answer
            final_response = response
            break
        
        # Process tool calls
        tool_results = []
        for tool_call in response["tool_calls"]:
            result = handle_tool_execution(tool_call["tool_name"], tool_call["input"])
            tool_results.append({
                "tool_use_id": tool_call["tool_id"],
                "content": json.dumps(result)
            })
        
        # Feed tool results back to agent
        if session_state is None:
            session_state = {"conversation_history": []}
        
        session_state["conversation_history"].append({
            "role": "user",
            "content": user_query
        })
        
        session_state["conversation_history"].append({
            "role": "assistant",
            "content": response["content"] + [
                {"type": "tool_use", "id": tc["tool_id"], "name": tc["tool_name"]}
                for tc in response["tool_calls"]
            ]
        })
        
        # Add tool results as system message for next iteration
        session_state["conversation_history"].append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tr["tool_use_id"], "content": tr["content"]}
                for tr in tool_results
            ]
        })
    
    return final_response or response


# Example usage:
if __name__ == "__main__":
    
    # Scenario 1: Contract summarization
    response = procure_agent(
        user_query="Summarize the Acme MSA and flag risks",
        document_context={
            "Acme_MSA_2024.pdf": {
                "summary": "100-page Master Service Agreement for cloud services..."
            }
        }
    )
    print(json.dumps(response, indent=2))
    
    # Scenario 2: Vendor Q&A with tool execution
    response = agentic_loop(
        user_query="Which vendors have contracts expiring next quarter?",
        document_context={},
        session_state={"user_preferences": {"currency": "USD"}}
    )
    print(json.dumps(response, indent=2))
```

================================================================================
2. FASTAPI BACKEND SETUP
================================================================================

```python
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from typing import Optional, List
from pydantic import BaseModel
import uuid

app = FastAPI(title="Procure.ai Backend")

# CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://procure.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ Data Models ============

class DocumentUpload(BaseModel):
    file_name: str
    doc_type: str  # "contract" | "spreadsheet"
    company_name: str
    user_id: str

class ConversationMessage(BaseModel):
    session_id: str
    user_query: str
    context: Optional[dict] = None

class ExportRequest(BaseModel):
    content: dict
    format: str = "standard"  # "standard" | "executive"
    file_format: str = "docx"  # "docx" | "pdf"

# ============ Endpoints ============

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...), company: str = None, user_id: str = None):
    """
    Handle contract/spreadsheet upload.
    Returns document metadata and initiates async processing.
    """
    doc_id = str(uuid.uuid4())
    
    try:
        # Save file to storage (S3 / local)
        content = await file.read()
        storage_path = save_to_storage(doc_id, content, file.filename)
        
        # Queue async processing
        task_id = queue_document_processing(
            doc_id=doc_id,
            file_path=storage_path,
            file_type=file.content_type,
            company=company,
            user_id=user_id
        )
        
        return JSONResponse({
            "doc_id": doc_id,
            "filename": file.filename,
            "status": "processing",
            "task_id": task_id,
            "estimated_time": "30 seconds"
        })
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/chat")
async def chat(request: ConversationMessage):
    """
    Main chat endpoint. Runs agent with user query.
    """
    try:
        response = agentic_loop(
            user_query=request.user_query,
            document_context=request.context,
            session_state=load_session(request.session_id)
        )
        
        # Save conversation to history
        save_conversation(request.session_id, request.user_query, response)
        
        return JSONResponse({
            "session_id": request.session_id,
            "response": response["content"],
            "tool_calls": response["tool_calls"],
            "timestamp": response["timestamp"]
        })
    
    except Exception as e:
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )

@app.get("/api/documents")
async def list_documents(user_id: str):
    """
    Retrieve user's document library.
    """
    docs = get_user_documents(user_id)
    return JSONResponse({
        "documents": docs,
        "count": len(docs)
    })

@app.get("/api/document/{doc_id}")
async def get_document(doc_id: str):
    """
    Fetch document metadata and analysis.
    """
    doc = retrieve_document(doc_id)
    return JSONResponse(doc)

@app.post("/api/analyze")
async def analyze_document(request: dict):
    """
    Trigger specific analysis on a document.
    body: { "doc_id": "...", "analysis_type": "summary|clauses|risks" }
    """
    doc_id = request.get("doc_id")
    analysis_type = request.get("analysis_type", "summary")
    
    result = execute_tool("process_contract", {
        "doc_id": doc_id,
        "extraction_type": analysis_type
    })
    
    return JSONResponse(result)

@app.post("/api/query")
async def query_spreadsheet(request: dict):
    """
    Execute natural language query against vendor data.
    body: { "query": "Which vendors expire next month?" }
    """
    # Use agent to interpret NL and generate SQL
    nl_query = request.get("query")
    
    # Could call agent to parse intent and generate query
    # Or: directly map common queries to SQL templates
    
    result = execute_tool("execute_query", {
        "spreadsheet_id": "vendor_master_db",
        "query": nl_to_sql(nl_query)
    })
    
    return JSONResponse({
        "query": nl_query,
        "results": result,
        "row_count": len(result)
    })

@app.post("/api/export")
async def export_report(request: ExportRequest):
    """
    Export analysis as DOCX/PDF.
    """
    result = execute_tool("export_to_docx", {
        "content": request.content,
        "format": request.format
    })
    
    # Stream file back to client
    return StreamingResponse(
        iter([result["file_bytes"]]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="report.docx"'}
    )

@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """
    Retrieve conversation history for a session.
    """
    session = load_session(session_id)
    return JSONResponse(session)

@app.post("/api/session/{session_id}/clear")
async def clear_session(session_id: str):
    """
    Reset conversation (keep documents).
    """
    clear_conversation_history(session_id)
    return JSONResponse({"status": "cleared"})

# ============ Health & Status ============

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "version": "1.0"})

@app.get("/api/status/{task_id}")
async def check_task_status(task_id: str):
    """
    Check async task progress (document processing).
    """
    status = get_task_status(task_id)
    return JSONResponse(status)

# ============ Stub Functions (Replace with actual implementations) ============

def save_to_storage(doc_id: str, content: bytes, filename: str) -> str:
    # Implement S3 or local file storage
    pass

def queue_document_processing(doc_id: str, file_path: str, file_type: str, company: str, user_id: str) -> str:
    # Queue with Celery / Redis / RQ
    pass

def execute_tool(tool_name: str, tool_input: dict) -> dict:
    # Delegate to tool execution (from agentic_loop)
    pass

def load_session(session_id: str) -> dict:
    # Retrieve from Redis / DB
    pass

def save_conversation(session_id: str, user_query: str, response: dict):
    # Persist to DB
    pass

def get_user_documents(user_id: str) -> list:
    # Query document store
    pass

def retrieve_document(doc_id: str) -> dict:
    # Get doc metadata + cached analysis
    pass

def nl_to_sql(nl_query: str) -> str:
    # Either use agent or template mapping
    pass

def get_task_status(task_id: str) -> dict:
    # Query async task queue
    pass

def clear_conversation_history(session_id: str):
    # Delete from Redis/DB
    pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

================================================================================
3. DEPLOYMENT ARCHITECTURE
================================================================================

Recommended Stack for MNC:

Frontend:
- React (provided in procurement_frontend.jsx)
- Hosted on: Vercel / AWS CloudFront / Azure App Service
- Auth: OAuth2 (AD/Okta integration for enterprise SSO)

Backend:
- FastAPI (Python 3.11+)
- Hosting: AWS ECS / Kubernetes / Azure Container Apps
- Database: PostgreSQL (document metadata, conversation logs)
- Cache: Redis (session state, conversation history)
- Message Queue: RabbitMQ / AWS SQS (async document processing)

LLM Backbone:
- Claude API (claude-opus-4-6 for complex reasoning)
- Alternative: OpenAI GPT-4, Google Gemini 2.5 Pro
- Token budget: ~100-200 tokens per user query average

Document Processing:
- PDF extraction: pdfplumber / pypdf / AWS Textract
- DOCX parsing: python-docx
- OCR: Tesseract / AWS Textract (for scanned PDFs)
- Storage: AWS S3 / Azure Blob Storage

Vector Database (RAG):
- FAISS (in-process, <100M documents)
- ChromaDB (persistent, distributed)
- Pinecone (managed, scalable)
- Embeddings: OpenAI text-embedding-3 / Gemini embeddings

Monitoring & Logging:
- Log aggregation: DataDog / Splunk / ELK
- APM: New Relic / Datadog
- Error tracking: Sentry
- Audit logs: CloudTrail / Azure Audit Logs

Security:
- API key management: AWS Secrets Manager / HashiCorp Vault
- Data encryption: TLS in transit, KMS/AES-256 at rest
- Access control: RBAC with role-based document access
- Compliance: SOC 2 Type II, GDPR ready, HIPAA if healthcare

================================================================================
4. TESTING & QA STRATEGY
================================================================================

Unit Tests:
- Test clause extraction against known contracts
- Test financial term parsing (amounts, currencies, dates)
- Test risk classification logic
- Test RFQ template generation

Integration Tests:
- Full conversation flow: upload → analyze → export
- Multi-document comparison
- API response times (<3s for Q&A, <30s for analysis)

Accuracy Benchmarks:
- Clause extraction: test against 50 contracts, 95%+ accuracy
- Risk detection: 90%+ recall on high-severity risks
- Payment term extraction: 99%+ for numerical amounts
- Date normalization: 98%+ for temporal clauses

Test Data:
- Create synthetic contracts with known structure
- Real contracts (anonymized) from partner companies
- Edge cases: ambiguous language, unusual payment terms, missing clauses

================================================================================
5. EXAMPLE REQUESTS & RESPONSES
================================================================================

Request 1: Contract Summary
-----
POST /api/chat
{
  "session_id": "user-123-session",
  "user_query": "Summarize the Acme MSA and what are the key risks?",
  "context": {
    "Acme_MSA_2024.pdf": {
      "doc_id": "doc-abc123",
      "uploaded": "2024-01-20T10:30Z"
    }
  }
}

Response:
{
  "session_id": "user-123-session",
  "response": [
    {
      "type": "text",
      "text": "Based on the Acme MSA:\n\n**Executive Summary**: 3-year cloud infrastructure contract valued at $2.5M, with automatic renewal.\n\n**Key Risks**:\n- HIGH: Liability cap is $100K, but contract value is $2.5M. Exposure exceeds cap by 25x.\n- MEDIUM: 90-day termination notice required. Consider negotiating 30-day clause for flexibility.\n- MEDIUM: No explicit SLA performance guarantee. Recommend adding 99.5% uptime requirement.\n\nRecommendation: Schedule renegotiation before auto-renewal (due 90 days before expiry on 2027-01-15)."
    }
  ],
  "timestamp": "2024-01-20T15:45Z"
}

Request 2: Vendor Q&A
-----
POST /api/query
{
  "query": "Which vendors have contracts expiring in the next 3 months and what's their total spend?"
}

Response:
{
  "query": "Which vendors have contracts expiring in the next 3 months and what's their total spend?",
  "results": [
    {
      "vendor_name": "Acme Corp",
      "contract_value": 2500000,
      "expiry_date": "2024-04-15",
      "status": "active",
      "days_until_expiry": 87
    },
    {
      "vendor_name": "TechVendor Inc",
      "contract_value": 1800000,
      "expiry_date": "2024-05-20",
      "status": "active",
      "days_until_expiry": 122
    }
  ],
  "total_spend": 4300000,
  "row_count": 2,
  "insight": "4.3M in vendor commitments expiring Q2. Recommend starting renewal RFQs immediately to allow 60-day evaluation window."
}

Request 3: RFQ Generation
-----
POST /api/chat
{
  "session_id": "user-123-session",
  "user_query": "Generate an RFQ for 50 new desktop computers, deployment in Q2 2024, inherit T&Cs from existing IT vendor contracts, response deadline 14 days.",
  "context": {}
}

Response (includes tool call):
{
  "session_id": "user-123-session",
  "response": [
    {
      "type": "text",
      "text": "I'm generating your RFQ for desktop computers. I've inherited standard terms from your existing IT vendor contracts to ensure consistency..."
    }
  ],
  "tool_calls": [
    {
      "tool_name": "export_to_docx",
      "tool_id": "tool-xyz",
      "input": {
        "content": {
          "header": { ... },
          "sections": { ... },
          "legal_footer": "..."
        },
        "format": "standard"
      }
    }
  ],
  "timestamp": "2024-01-20T15:50Z"
}

================================================================================
END OF INTEGRATION GUIDE
================================================================================

This guide covers API integration, FastAPI setup, deployment architecture, and testing strategies for deploying Procure.ai as a production SaaS platform. Adapt the code to your infrastructure and LLM provider of choice.

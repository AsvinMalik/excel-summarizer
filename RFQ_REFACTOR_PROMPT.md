# RFQ Feature Refactor - CLI Prompt

## TASK: Replace Manual RFQ Generator with Smart RFQ Detection

### CURRENT PROBLEM
- RFQBuilder.jsx has manual "Generate RFQ" form (9 input fields)
- User manually fills everything and generates template
- Not data-driven
- Doesn't analyze actual contracts or vendor performance
- Wastes procurement team's time

### SOLUTION: Smart RFQ Detection Engine

Replace the manual RFQ form with an intelligent system that:

1. **Analyzes uploaded contracts** to identify which need RFQs
2. **Suggests RFQs automatically** based on:
   - Contract expiration dates (< 90 days)
   - Vendor performance scores (< 70%)
   - Pricing anomalies (above market average)
   - Compliance risks
   - Renewal opportunities
3. **Pre-fills RFQ data** from existing contracts
4. **Lets user review & adjust** before generating

---

## NEW WORKFLOW

### Step 1: User Uploads Vendor Data
```
User uploads: vendor_contracts.xlsx
Backend: Reads and analyzes data
```

### Step 2: System Suggests RFQs
```
Display in UI:
┌────────────────────────────────────────┐
│ 📊 RFQ OPPORTUNITIES DETECTED          │
├────────────────────────────────────────┤
│ ✅ 5 contracts expiring in 90 days     │
│ ⚠️  3 vendors below performance target │
│ 🔴 2 high-risk compliance issues       │
│                                        │
│ [Review Suggestions] [Generate RFQs]  │
└────────────────────────────────────────┘
```

### Step 3: User Reviews Suggestions
```
Display each contract:
├─ Vendor: Acme Corp
├─ Contract Value: $500K/year
├─ Expiration: August 15, 2026 (46 days)
├─ Performance Score: 72% (below 75% target)
├─ Reason for RFQ: Expiring + Low performance
└─ [Generate RFQ] [Skip] [Snooze]
```

### Step 4: Auto-Fill & Generate
```
System creates RFQ with:
├─ Company details (from contract)
├─ Scope (from previous contract)
├─ Terms (from contract history)
├─ Quality standards (from performance metrics)
└─ Evaluation criteria (company defaults)

User can:
✓ Review auto-filled data
✓ Adjust before finalizing
✓ Add custom requirements
✓ Generate final document
```

---

## FILES TO MODIFY

### 1. **backend/services.py**
- Add function: `detect_rfq_candidates(contracts_data)`
- Returns: List of contracts needing RFQs with reasons
- Add function: `extract_rfq_template(contract_data)`
- Returns: Pre-filled RFQ structure from contract

### 2. **src/components/RFQBuilder.jsx**
- Remove: Manual form with 9 input fields
- Add: "Analyze Contracts" button
- Add: RFQ suggestions panel showing detected opportunities
- Add: Review panel for each suggestion
- Keep: Final RFQ draft preview

### 3. **backend/main.py**
- Add endpoint: `POST /api/analyze-for-rfq`
  - Input: uploaded contracts
  - Output: suggested RFQs with reasons
- Add endpoint: `POST /api/auto-fill-rfq`
  - Input: contract_id, vendor_id
  - Output: pre-filled RFQ data

---

## DETECTION LOGIC

```python
def detect_rfq_candidates(contracts_data):
    candidates = []
    
    for contract in contracts_data:
        reasons = []
        
        # Check 1: Expiration (< 90 days)
        days_until_expiry = (contract.end_date - today).days
        if 0 < days_until_expiry < 90:
            reasons.append(f"Expires in {days_until_expiry} days")
        
        # Check 2: Performance score
        if contract.vendor_score < 75:
            reasons.append(f"Low performance: {contract.vendor_score}%")
        
        # Check 3: Pricing anomaly
        if contract.price > market_average * 1.2:
            reasons.append(f"Price {20}% above market average")
        
        # Check 4: Compliance risk
        if contract.compliance_flags:
            reasons.append(f"Compliance issues: {', '.join(flags)}")
        
        if reasons:
            candidates.append({
                "vendor": contract.vendor_name,
                "value": contract.annual_value,
                "expiry": contract.end_date,
                "score": contract.vendor_score,
                "reasons": reasons,
                "priority": calculate_priority(reasons)
            })
    
    return sorted(candidates, key=lambda x: x['priority'], reverse=True)
```

---

## UI COMPONENTS

### Component 1: Detection Panel
```jsx
<RFQDetectionPanel>
  - Shows analysis results
  - Lists detected opportunities
  - Buttons: Analyze, Review, Generate
</RFQDetectionPanel>
```

### Component 2: Suggestion Card
```jsx
<RFQSuggestionCard contract={contract}>
  - Vendor name & contract value
  - Expiration date
  - Performance score
  - Reasons (badges)
  - Actions: [Generate] [Skip] [Snooze]
</RFQSuggestionCard>
```

### Component 3: Review Panel
```jsx
<RFQReviewPanel rfqData={preFilledData}>
  - Pre-filled fields from contract
  - User can edit each field
  - Shows what was auto-filled
  - [Generate RFQ] [Cancel]
</RFQReviewPanel>
```

---

## DATA FLOW

```
User uploads Excel
    ↓
/api/analyze-for-rfq endpoint
    ↓
detect_rfq_candidates(data)
    ↓
Return list with:
{
  vendor: "Acme Corp",
  value: 500000,
  expiry: "2026-08-15",
  score: 72,
  reasons: ["Expires in 46 days", "Below target score"],
  priority: "high"
}
    ↓
Display in UI (RFQDetectionPanel)
    ↓
User clicks [Generate RFQ]
    ↓
/api/auto-fill-rfq endpoint
    ↓
extract_rfq_template(contract)
    ↓
Return pre-filled structure:
{
  company_name: "Acme Corp",
  scope_of_work: [...],
  terms_and_conditions: [...],
  quantity: 100,
  ...
}
    ↓
Display in RFQReviewPanel
    ↓
User reviews & adjusts
    ↓
User clicks [Generate RFQ Draft]
    ↓
Final RFQ document created ✅
```

---

## BENEFITS

| Aspect | Before | After |
|--------|--------|-------|
| **Data-driven** | ❌ Manual | ✅ Automatic detection |
| **Speed** | 20 min per RFQ | 2 min per RFQ |
| **Accuracy** | User dependent | System validated |
| **Completeness** | May miss items | Never misses expiries |
| **Compliance** | Manual checking | Automatic flagging |
| **Scalability** | 5-10 RFQs/month | 50+ RFQs/month |

---

## IMPLEMENTATION PHASES

### Phase 1: Detection Engine
- Implement `detect_rfq_candidates()` function
- Create `/api/analyze-for-rfq` endpoint
- Test with sample data

### Phase 2: UI Components
- Build RFQDetectionPanel
- Build RFQSuggestionCard
- Build RFQReviewPanel

### Phase 3: Auto-Fill
- Implement `extract_rfq_template()` function
- Create `/api/auto-fill-rfq` endpoint
- Connect to review panel

### Phase 4: Polish
- Add sorting/filtering
- Add snooze functionality
- Add batch generation
- Add export to Word

---

## SUCCESS CRITERIA

✅ System detects all contracts expiring in 90 days  
✅ Flagged contracts show reasons  
✅ RFQ pre-filled with 80%+ accuracy  
✅ User can generate in < 1 minute  
✅ Export as professional document  
✅ Reduce RFQ creation time by 80%  

---

## QUICK START COMMAND

```bash
# Implement detection logic
claude code "Refactor RFQ feature: Replace manual form with smart detection. 
Follow SOLUTION section in RFQ_REFACTOR_PROMPT.md. 
Focus on: 
1. Detect contracts needing RFQs (expiry, performance, pricing)
2. Display suggestions in UI
3. Auto-fill RFQ from contract data
4. Let user review before generating"
```


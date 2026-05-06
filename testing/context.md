I am building an **AI-powered Tender Evaluation System**. The first implementation phase is **dynamic tender parsing and chunking** so the system can later perform criteria extraction, submission matching, evaluation, and auditability.

### What we are building

We are creating a **hierarchical chunking pipeline** for tender PDFs:

* **L0 → Section / Parent Chunk**

  * Example: "Bid Details", "Financial Criteria", "Technical Specifications"

* **L1 → Semantic Child Chunk**

  * For tables → each row becomes one L1 chunk
  * Example: "Minimum Average Annual Turnover : 1 Lakh"

* **L2 → Atomic Child Chunk**

  * Split only when value is a flat list
  * Example:

    * Experience Criteria
    * Past Performance
    * Bidder Turnover
  * Do NOT split conditional phrases or numeric requirements

Every chunk must store metadata:

* page number
* heading
* row_key
* original_value
* chunk_type
* parent_id
* children

This hierarchy will power:

* evaluation engine
* explainable reports
* chatbot retrieval
* audit trail

---

### Current implementation

We are using Python with:

* PyMuPDF / pdfplumber for PDF extraction
* Dataclass-based Chunk model
* Recursive hierarchy creation
* Splitter logic for flat lists vs conditional values

We already implemented:

* table extraction
* L0/L1/L2 chunk creation
* metadata attachment
* intelligent comma splitting rules

---

### Current challenge

Tender PDFs are bilingual.

Pattern:

Left table column (keys):
Hindi / English

Example:
बिड बंद होने की तारीख/समय / Bid End Date/Time

Right table column (values):
English only

Example:
05-05-2026 10:00:00

Current issue:
normalization logic is removing too much content or affecting values.

Correct expected behavior:

**For LEFT column only**
Normalize:
बिड बंद होने की तारीख/समय / Bid End Date/Time
→ Bid End Date/Time

**For RIGHT column**
Do NOT modify content.
Keep exactly as extracted:
05-05-2026 10:00:00
1 Lakh (s)
50 %
GEM/2026/B/7475677

Also preserve raw metadata:

* raw_key
* normalized_key
* raw_value
* normalized_value

---

### What I need implemented

Build a robust normalization layer before chunk creation:

Pipeline:
PDF Extraction
→ Normalize LEFT column only
→ Keep RIGHT column untouched
→ Create chunk hierarchy
→ Attach metadata
→ Output JSON

Need clean, production-grade Python code integrated into the current chunking pipeline.

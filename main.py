from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import os
import re
import numpy as np
from typing import Dict, List, Optional, Tuple
from PyPDF2 import PdfReader
import spacy
from gtts import gTTS
from sentence_transformers import SentenceTransformer
import numpy.linalg as LA

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

nlp = spacy.load("en_core_web_sm")

AUDIO_DIR = os.path.join(tempfile.gettempdir(), "legalease_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# Global in-memory document store for RAG
DOC_STORE: Dict[str, dict] = {}
EMBED_MODEL = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')


def py(v):
    """Safely convert numpy types to Python native types for JSON serialization."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def extract_text_from_pdf(path: str) -> str:
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _clean_name(name: str) -> str:
    name = re.sub(r'[^A-Za-z.\s]', '', name).strip()
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_role_parties(text: str) -> dict:
    """
    Try to extract Vendor and Purchaser style parties from typical Sale Deed format.
    Falls back to None if not found.
    """
    # Capture line after VENDOR / PURCHASER headings
    vendor = None
    purchaser = None

    vendor_match = re.search(
        r'(VENDOR|SELLER)[^\n]*\n\s*(Mr\.|Ms\.|Mrs\.)?\s*([A-Za-z .]+)',
        text,
        flags=re.IGNORECASE
    )
    if vendor_match:
        vendor = _clean_name(vendor_match.group(3))

    purchaser_match = re.search(
        r'(PURCHASER|BUYER)[^\n]*\n\s*(Mr\.|Ms\.|Mrs\.)?\s*([A-Za-z .]+)',
        text,
        flags=re.IGNORECASE
    )
    if purchaser_match:
        purchaser = _clean_name(purchaser_match.group(3))

    # If not found, try BETWEEN ... AND blocks
    if not vendor:
        between_vendor = re.search(
            r'BETWEEN\s+.*?\n\s*(Mr\.|Ms\.|Mrs\.)?\s*([A-Za-z .]+),',
            text,
            flags=re.IGNORECASE | re.DOTALL
        )
        if between_vendor:
            vendor = _clean_name(between_vendor.group(2))

    if not purchaser:
        between_purchaser = re.search(
            r'\bAND\b\s+.*?\n\s*(Mr\.|Ms\.|Mrs\.)?\s*([A-Za-z .]+),',
            text,
            flags=re.IGNORECASE | re.DOTALL
        )
        if between_purchaser:
            purchaser = _clean_name(between_purchaser.group(2))

    return {"vendor": vendor, "purchaser": purchaser}


def extract_property_details(text: str) -> dict:
    # Capture ONLY until newline (no spillover into next label)
    def first_line_value(label: str):
        m = re.search(rf"{label}\s*[:\-]?\s*([^\n\r]+)", text, flags=re.IGNORECASE)
        return m.group(1).strip() if m else None

    survey_no = first_line_value("Survey No")
    patta_no = first_line_value("Patta No")
    village = first_line_value("Village")
    taluk = first_line_value("Taluk")
    district = first_line_value("District")

    # fallback: if District: line is missing/empty, use "X District, Tamil Nadu" from header
    if not district or district.strip() in {",", ", Tamil Nadu"}:
        m = re.search(r"([A-Za-z\s]+)\s+District,\s*Tamil Nadu", text, flags=re.IGNORECASE)
        if m:
            district = m.group(1).strip()

    # Extra cleanup: remove trailing label words if they got attached
    def clean(v: str | None):
        if not v:
            return None
        v = re.sub(r"\b(Taluk|District|BOUNDARIES)\b.*$", "", v, flags=re.IGNORECASE).strip()
        return v

    return {
        "survey_no": clean(survey_no),
        "patta_no": clean(patta_no),
        "village": clean(village),
        "taluk": clean(taluk),
        "district": clean(district),
    }


def extract_facts(text: str):
    doc = nlp(text)

    # Parties
    parties = []
    role_parties = extract_role_parties(text)
    if role_parties["vendor"]:
        parties.append(role_parties["vendor"])
    if role_parties["purchaser"]:
        parties.append(role_parties["purchaser"])

    # Dates + amounts
    dates = []
    amounts = []

    # A) Regex capture for dd-mm-yyyy / dd/mm/yyyy (numeric dates first)
    date_matches = re.findall(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", text)
    dates.extend(date_matches)

    # Amount detection (avoid picking pin codes / document numbers)
    amount_patterns = [
        r'Rs\.?\s*[\d,]+(?:\.\d+)?\s*/?-?',   # Rs. 25,00,000/-
        r'₹\s*[\d,]+(?:\.\d+)?',              # ₹25,00,000
        r'Rupees\s+[A-Za-z\s]+Only',          # Rupees Twenty Five Lakhs Only
        r'[\d,]+\s*Lakhs',                    # 25 Lakhs / 25,00,000 style text
    ]

    for pattern in amount_patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        for match in matches:
            # Keep only amounts that clearly look like money,
            # and try to filter out small numbers
            digits = re.sub(r'[^0-9]', '', match)
            if digits.isdigit() and int(digits) >= 1000:
                amounts.append(match.strip())

    # spaCy entities (fallback)
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            parties.append(ent.text)
        elif ent.label_ == "DATE":
            dates.append(ent.text)
        elif ent.label_ == "MONEY":
            amounts.append(ent.text)

    # Filter out obvious non-party noise
    bad_words = {
        "Tamil Nadu", "Anna Nagar", "Gandhi Street", "Coimbatore",
        "Challan", "Peelamedu", "Perur", "District", "Taluk", "Village"
    }
    parties = [p.strip() for p in parties if p and all(w.lower() not in p.lower() for w in bad_words)]

    # De-dup and limit
    parties = list(dict.fromkeys(parties))[:4]
    dates = list(dict.fromkeys(dates))

    # remove age + pure numbers like pin codes + "the day, month" + doc numbers
    clean_dates = []
    for d in dates:
        dl = d.lower().strip()
        if "years" in dl:
            continue
        # Filter "the day, month"
        if "the day, month" in dl:
            continue
        # remove "2145 / 2025" style (document no/year)
        if re.fullmatch(r"\d+\s*/\s*\d+", d.strip()):
            continue
        # remove incomplete phrase
        if dl.startswith("this 15th day"):
            continue
        # if it's only digits (like 641004), skip
        if re.fullmatch(r"\d{4,}", d.strip()):
            continue
        clean_dates.append(d)

    dates = clean_dates[:4]
    amounts = list(dict.fromkeys(amounts))[:4]

    # Property details
    property_details = extract_property_details(text)

    return {
        "parties": parties,
        "role_parties": role_parties,         # vendor/purchaser (if detected)
        "dates": dates,
        "amounts": amounts,
        "property": property_details,         # survey/patta/village/taluk/district
    }


def compute_risk_color(facts: dict):
    missing = []
    if len(facts.get("parties", [])) < 2:
        missing.append("parties")
    if len(facts.get("dates", [])) < 1:
        missing.append("dates")
    if len(facts.get("amounts", [])) < 1:
        missing.append("amounts")

    # Optional land fields (don't mark missing as "risky" yet; just informative)
    prop = facts.get("property", {}) or {}
    if not prop.get("survey_no"):
        missing.append("survey_no")
    if not prop.get("patta_no"):
        missing.append("patta_no")

    # Risk color based on core fields only
    core_missing = [m for m in missing if m in {"parties", "dates", "amounts"}]
    if len(core_missing) == 0:
        color = "Green"
    elif len(core_missing) == 1:
        color = "Orange"
    else:
        color = "Red"

    return {"color": color, "missing_fields": missing}


def simple_english_summary(text: str, facts: dict, risk: dict) -> str:
    role_parties = facts.get("role_parties", {}) or {}
    vendor = role_parties.get("vendor")
    purchaser = role_parties.get("purchaser")

    parties_fallback = ", ".join(facts.get("parties", [])[:2]) if len(facts.get("parties", [])) >= 2 else "the parties involved"
    date = facts.get("dates", [None])[0] or "the specified date"
    amount = facts.get("amounts", [None])[0] or "the agreed consideration"

    doc_type = "Sale Deed" if "SALE DEED" in text.upper() else "Legal Document"
    prop = facts.get("property", {}) or {}

    who_line = f"{vendor} (seller) → {purchaser} (buyer)" if vendor and purchaser else parties_fallback
    prop_line = []
    if prop.get("survey_no"):
        prop_line.append(f"Survey No: {prop['survey_no']}")
    if prop.get("patta_no"):
        prop_line.append(f"Patta No: {prop['patta_no']}")
    if prop_line:
        prop_text = " | ".join(prop_line)
    else:
        prop_text = "Property identifiers not clearly detected."

    if risk["color"] == "Green":
        risk_text = "No major missing fields detected. Proceed only after a standard legal review."
    elif risk["color"] == "Orange":
        risk_text = f"Some key fields may be missing ({', '.join(risk['missing_fields'])}). Review before proceeding."
    else:
        risk_text = f"Important fields missing ({', '.join(risk['missing_fields'])}). Not safe to proceed without verification."

    return (
        f"{doc_type}: {who_line}. "
        f"Date reference: {date}. Consideration/amount: {amount}. "
        f"{prop_text}. "
        f"Risk check: {risk_text}"
    )


def full_tamil_summary(text: str, facts: dict, risk: dict) -> str:
    role_parties = facts.get("role_parties", {}) or {}
    vendor = role_parties.get("vendor")
    purchaser = role_parties.get("purchaser")

    date = facts.get("dates", [None])[0] or "குறிப்பிட்ட தேதி"
    amount = facts.get("amounts", [None])[0] or "ஒப்பந்தத் தொகை"

    doc_type = "விற்பனை ஒப்பந்தம்" if "SALE DEED" in text.upper() or "விற்பனை" in text else "சட்ட ஆவணம்"

    # Who to whom (Tamil)
    if vendor and purchaser:
        who_line = f"இந்த ஆவணத்தில் {vendor} அவர்கள் விற்பனையாளராகவும், {purchaser} அவர்கள் வாங்குபவராகவும் உள்ளனர்."
    else:
        parties = facts.get("parties", [])
        if len(parties) >= 2:
            who_line = f"இந்த ஆவணம் {parties[0]} மற்றும் {parties[1]} ஆகியோருக்கிடையிலான ஒப்பந்தம் போல தெரிகிறது."
        else:
            who_line = "இந்த ஆவணத்தில் உள்ள தரப்பினர்கள் தெளிவாக கண்டறியப்படவில்லை."

    # Property details (Tamil)
    prop = facts.get("property", {}) or {}
    prop_parts = []
    if prop.get("survey_no"):
        prop_parts.append(f"சர்வே எண்: {prop['survey_no']}")
    if prop.get("patta_no"):
        prop_parts.append(f"பட்டா எண்: {prop['patta_no']}")
    if prop.get("village"):
        prop_parts.append(f"கிராமம்: {prop['village']}")
    if prop.get("taluk"):
        prop_parts.append(f"தாலூக்கம்: {prop['taluk']}")
    if prop.get("district"):
        prop_parts.append(f"மாவட்டம்: {prop['district']}")
    prop_text = " | ".join(prop_parts) if prop_parts else "சொத்து அடையாள விவரங்கள் (சர்வே/பட்டா) தெளிவாக கிடைக்கவில்லை."

    # Risk message (Tamil) based on core fields only
    core_missing = [m for m in risk["missing_fields"] if m in {"parties", "dates", "amounts"}]
    if risk["color"] == "Green":
        risk_msg = "முக்கிய தகவல்கள் கிடைத்துள்ளன. வழக்கமான சட்ட சரிபார்ப்பிற்குப் பிறகு மட்டுமே செயல்படவும்."
    elif risk["color"] == "Orange":
        risk_msg = f"சில முக்கிய தகவல்கள் குறைவாக இருக்கலாம் ({', '.join(core_missing)}). செயல்படுவதற்கு முன் சரிபார்க்கவும்."
    else:
        risk_msg = f"முக்கிய தகவல்கள் குறைவாக உள்ளன ({', '.join(core_missing)}). முழுமையாக சரிபார்க்காமல் தொடர வேண்டாம்."

    tamil_summary = (
        f"{doc_type}. {who_line} "
        f"தேதி: {date}. முக்கிய தொகை: {amount}. "
        f"{prop_text}. "
        f"அபாய மதிப்பீடு: {risk_msg}"
    )
    return tamil_summary


def snippet_around(text: str, query: str, window: int = 260) -> str:
    """Extract a snippet around query keywords in the text."""
    # Extract meaningful query words (longer than 3 chars)
    q_words = [w.lower() for w in re.findall(r"[a-zA-Z]+", query) if len(w) > 3]
    low = text.lower()
    
    # Find positions of query words in text
    hits = [low.find(w) for w in q_words if low.find(w) != -1]
    
    # If no query words found, return beginning of text
    if not hits:
        return text[:window] + ("..." if len(text) > window else "")
    
    # Take the earliest occurrence
    pos = min(hits)
    
    # Center snippet around the found position
    start = max(0, pos - window // 2)
    end = min(len(text), start + window)
    
    # Adjust start if we're too close to the beginning
    if start == 0 and end < len(text):
        return text[:end] + "..."
    elif end == len(text) and start > 0:
        return "..." + text[start:]
    elif start > 0 and end < len(text):
        return "..." + text[start:end] + "..."
    else:
        return text[start:end]


def chunk_text(text: str, chunk_size: int = 160, overlap: int = 40) -> List[str]:
    """Split text into overlapping chunks."""
    chunks = []
    words = text.split()
    
    for i in range(0, len(words), chunk_size - overlap):
        chunk = ' '.join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
            if i + chunk_size >= len(words):
                break
    return chunks


def build_document_index(text: str, document_id: str, facts: dict) -> dict:
    """Build RAG index for a document."""
    # Clean text before chunking
    clean_text = re.sub(r'\s+', ' ', text).strip()
    
    # Create chunks
    chunks = chunk_text(clean_text)
    
    # Generate embeddings for chunks
    chunk_embeddings = EMBED_MODEL.encode(chunks, normalize_embeddings=True)
    
    # Store in DOC_STORE with facts
    DOC_STORE[document_id] = {
        "chunks": chunks,
        "embeddings": chunk_embeddings,
        "text": text,
        "facts": facts  # Store extracted facts
    }
    
    return {
        "document_id": document_id,
        "num_chunks": py(len(chunks)),
        "avg_chunk_length": py(sum(len(c) for c in chunks) / len(chunks) if chunks else 0)
    }


def detect_intent_and_answer(question: str, facts: dict) -> Tuple[bool, str, str]:
    """Detect if question is about structured facts and answer directly."""
    q_lower = question.lower()
    
    # Parties intent
    party_keywords = ["party", "parties", "vendor", "purchaser", "buyer", "seller", "who", "name", "person"]
    if any(keyword in q_lower for keyword in party_keywords):
        role_parties = facts.get("role_parties", {})
        vendor = role_parties.get("vendor")
        purchaser = role_parties.get("purchaser")
        
        if vendor and purchaser:
            answer = f"Vendor (seller): {vendor}, Purchaser (buyer): {purchaser}"
            if "vendor" in q_lower or "seller" in q_lower:
                answer = f"Vendor/Seller: {vendor}"
            elif "purchaser" in q_lower or "buyer" in q_lower:
                answer = f"Purchaser/Buyer: {purchaser}"
            return True, "parties", answer
        
        parties_list = facts.get("parties", [])
        if parties_list:
            return True, "parties", f"Parties involved: {', '.join(parties_list)}"
    
    # Amount intent
    amount_keywords = ["amount", "price", "consideration", "rupees", "rs", "₹", "money", "payment", "cost", "value"]
    if any(keyword in q_lower for keyword in amount_keywords):
        amounts = facts.get("amounts", [])
        if amounts:
            primary_amount = amounts[0] if amounts else "Not specified"
            all_amounts = ", ".join(amounts) if len(amounts) > 1 else primary_amount
            if len(amounts) > 1:
                return True, "amount", f"Multiple amounts mentioned: {all_amounts}. Primary amount: {primary_amount}"
            return True, "amount", f"Amount/consideration: {primary_amount}"
    
    # Property intent
    property_keywords = ["property", "land", "survey", "patta", "village", "taluk", "district", "location", "address"]
    if any(keyword in q_lower for keyword in property_keywords):
        prop = facts.get("property", {})
        if prop:
            answer_parts = []
            if prop.get("survey_no"):
                answer_parts.append(f"Survey No: {prop['survey_no']}")
            if prop.get("patta_no"):
                answer_parts.append(f"Patta No: {prop['patta_no']}")
            if prop.get("village"):
                answer_parts.append(f"Village: {prop['village']}")
            if prop.get("taluk"):
                answer_parts.append(f"Taluk: {prop['taluk']}")
            if prop.get("district"):
                answer_parts.append(f"District: {prop['district']}")
            
            if answer_parts:
                # Specific property field queries
                if "survey" in q_lower:
                    return True, "property", f"Survey Number: {prop.get('survey_no', 'Not specified')}"
                elif "patta" in q_lower:
                    return True, "property", f"Patta Number: {prop.get('patta_no', 'Not specified')}"
                elif "village" in q_lower:
                    return True, "property", f"Village: {prop.get('village', 'Not specified')}"
                elif "taluk" in q_lower:
                    return True, "property", f"Taluk: {prop.get('taluk', 'Not specified')}"
                elif "district" in q_lower:
                    return True, "property", f"District: {prop.get('district', 'Not specified')}"
                
                return True, "property", f"Property details: {' | '.join(answer_parts)}"
    
    # Dates intent
    date_keywords = ["date", "when", "executed", "signed", "day", "month", "year", "time"]
    if any(keyword in q_lower for keyword in date_keywords):
        dates = facts.get("dates", [])
        if dates:
            primary_date = dates[0] if dates else "Not specified"
            all_dates = ", ".join(dates) if len(dates) > 1 else primary_date
            if len(dates) > 1:
                return True, "dates", f"Multiple dates mentioned: {all_dates}. Primary date: {primary_date}"
            return True, "dates", f"Document date: {primary_date}"
    
    return False, "", ""


def search_document(question: str, document_id: str, top_k: int = 3) -> dict:
    """Search for relevant chunks in a document using cosine similarity."""
    if document_id not in DOC_STORE:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc_data = DOC_STORE[document_id]
    chunks = doc_data["chunks"]
    chunk_embeddings = doc_data["embeddings"]
    facts = doc_data.get("facts", {})
    
    # Step 1: Check if question can be answered from structured facts
    is_fact_based, intent_type, fact_answer = detect_intent_and_answer(question, facts)
    if is_fact_based:
        return {
            "answer": fact_answer,
            "sources": [{
                "chunk_id": -1,
                "score": 1.0,
                "text": f"Answer based on extracted {intent_type} information."
            }],
            "best_score": 1.0,
            "answer_source": "structured_facts",
            "intent_type": intent_type
        }
    
    # Step 2: Use retrieval for other questions
    # Encode question
    question_embedding = EMBED_MODEL.encode([question], normalize_embeddings=True)[0]
    
    # Compute cosine similarities (since embeddings are normalized, dot product = cosine similarity)
    similarities = np.dot(chunk_embeddings, question_embedding)
    
    # Get top-k indices
    top_indices = np.argsort(similarities)[-top_k:][::-1]
    
    # Check confidence threshold
    best_score = py(similarities[top_indices[0]]) if top_indices.size > 0 else 0.0
    
    # Step 3: Confidence threshold for retrieval answers
    if best_score < 0.25:
        return {
            "answer": "I'm not confident about the answer. Try asking about specific fields like 'Vendor', 'Purchaser', 'Amount', 'Survey Number', or 'Property details'.",
            "sources": [],
            "best_score": best_score,
            "answer_source": "low_confidence",
            "intent_type": "general"
        }
    
    # Step 4: Prepare results with safe type conversion
    sources = []
    for idx in top_indices:
        chunk_text = chunks[idx]
        # Get snippet for this chunk based on the question
        snippet = snippet_around(chunk_text, question)
        sources.append({
            "chunk_id": py(idx),
            "score": py(similarities[idx]),
            "text": snippet
        })
    
    # Generate answer from the best matching chunk
    best_chunk = chunks[top_indices[0]] if top_indices.size > 0 else ""
    answer_text = snippet_around(best_chunk, question, window=300)
    
    return {
        "answer": answer_text,
        "sources": sources,
        "best_score": best_score,
        "answer_source": "retrieval",
        "intent_type": "general",
        "top_indices": [py(i) for i in top_indices]  # For debugging
    }


@app.post("/analyze")
async def analyze_document(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        text = extract_text_from_pdf(tmp_path)
    finally:
        os.remove(tmp_path)

    facts = extract_facts(text)
    risk = compute_risk_color(facts)

    eng_summary = simple_english_summary(text, facts, risk)
    ta_summary = full_tamil_summary(text, facts, risk)

    # Tamil audio
    audio_filename = next(tempfile._get_candidate_names()) + ".mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)
    tts = gTTS(text=ta_summary, lang="ta", slow=False)
    tts.save(audio_path)

    # Build RAG index
    document_id = next(tempfile._get_candidate_names())
    index_info = build_document_index(text, document_id, facts)

    return {
        "document_id": document_id,
        "index_info": index_info,
        "doc_text": text[:5000],
        "facts": facts,
        "summaries": {
            "english": eng_summary,
            "tamil": ta_summary,
        },
        "audio": {
            "tamil_summary_mp3_url": f"/audio/{audio_filename}",
        },
        "risk": risk,
    }


@app.post("/ask")
async def ask_question(request: dict):
    """Ask a question about a specific document using RAG."""
    document_id = request.get("document_id")
    question = request.get("question")
    
    if not document_id or not question:
        raise HTTPException(status_code=400, detail="Missing document_id or question")
    
    try:
        result = search_document(question, document_id)
        return {
            "question": question,
            "answer": result["answer"],
            "sources": result["sources"],
            "best_similarity": result["best_score"],
            "answer_source": result.get("answer_source", "retrieval"),
            "intent_type": result.get("intent_type", "general"),
            "top_indices": result.get("top_indices", [])  # For debugging
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing question: {str(e)}")


@app.get("/documents")
async def list_documents():
    """List all documents in the store."""
    return {
        "documents": list(DOC_STORE.keys()),
        "count": py(len(DOC_STORE))
    }


@app.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    """Remove a document from the store."""
    if document_id in DOC_STORE:
        del DOC_STORE[document_id]
        return {"message": f"Document {document_id} deleted"}
    else:
        raise HTTPException(status_code=404, detail="Document not found")


@app.get("/audio/{filename}")
async def get_audio(filename: str):
    path = os.path.join(AUDIO_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path, media_type="audio/mpeg")
    return {"error": "Audio not found"}
# CLAUDE.md — ZukoLabs Virtual Try-On (VTO) System

> **Owner:** Chaitanya Kumar Manda | ZukoLabs  
> **Stack:** Python FastAPI · Supabase · Groq (Llama 3.3-70b-versatile) · Meta WhatsApp Cloud API · Replicate · Render.com  
> **Purpose:** WhatsApp-native AI Virtual Try-On SaaS for Indian D2C fashion, jewelry, and lifestyle sellers  
> **Last Updated:** June 2026

---

## SYSTEM OVERVIEW

ZukoLabs VTO is a multi-tenant, WhatsApp-native virtual try-on platform. Sellers (boutiques, D2C brands, jewellers) subscribe and get a dedicated WhatsApp-powered try-on bot for their customers. Customers send a selfie + product reference → receive a photorealistic try-on composite image in under 30 seconds — all inside WhatsApp, zero app download required.

The system is built as a **hybrid chatbot + mini-agent architecture**:
- **Chatbot flows** handle 80% of interactions (single-item try-on, consent, deletion, help)
- **Mini-agent flows** handle complex intents (occasion-based discovery, fit verification, skin tone advisory) — max 3 tool calls per agent run, never unbounded

---

## REPOSITORY STRUCTURE

```
zukolabs-vto/
├── CLAUDE.md                         # ← You are here
├── main.py                           # FastAPI app entry point
├── requirements.txt
├── .env.example
├── render.yaml                       # Render.com deployment config
│
├── api/
│   ├── webhook.py                    # Meta WhatsApp Cloud API webhook handler
│   ├── health.py                     # /health endpoint
│   └── admin.py                      # Seller dashboard API routes
│
├── core/
│   ├── config.py                     # Settings from env vars
│   ├── database.py                   # Supabase client init
│   ├── security.py                   # HMAC webhook verification
│   └── constants.py                  # Plan features, limits, enums
│
├── flows/
│   ├── intent_router.py              # Groq intent classifier → routes to correct flow
│   ├── consent_flow.py               # DPDP-compliant consent collection
│   ├── tryon_flow.py                 # Core try-on chatbot flow
│   ├── occasion_agent.py             # Mini-agent: occasion-based outfit discovery
│   ├── fit_verification_flow.py      # Post-purchase fit check flow
│   ├── catalog_flow.py               # Seller catalog browsing
│   ├── deletion_flow.py              # DPDP right-to-erasure flow
│   └── help_flow.py                  # Help / FAQ flow
│
├── services/
│   ├── whatsapp.py                   # WhatsApp Cloud API send/receive
│   ├── tryon_engine.py               # Replicate VITON API wrapper
│   ├── groq_client.py                # Groq LLM calls with retry + backoff
│   ├── skin_tone.py                  # CV skin tone detection from selfie
│   ├── catalog.py                    # Catalog search + filter
│   ├── image_store.py                # Supabase Storage + TTL deletion
│   └── voice_transcription.py        # Whisper API for vernacular voice messages
│
├── models/
│   ├── tenant.py                     # Seller/tenant Pydantic models
│   ├── customer.py                   # Customer session models
│   ├── tryon.py                      # Try-on job models
│   └── consent.py                    # Consent record models
│
├── middleware/
│   ├── idempotency.py                # Processed messages dedup
│   ├── rate_limiter.py               # Per-tenant rate limiting
│   └── tenant_resolver.py            # phone_number_id → tenant lookup
│
└── tests/
    ├── test_flows.py
    ├── test_tryon_engine.py
    └── test_dpdp_compliance.py
```

---

## ENVIRONMENT VARIABLES

All secrets via `.env`. Never hardcode. Never commit `.env`.

```bash
# Meta WhatsApp Cloud API
WHATSAPP_TOKEN=                    # Bearer token
WHATSAPP_VERIFY_TOKEN=             # Webhook verification token
WHATSAPP_APP_SECRET=               # For HMAC signature verification

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=              # Service role key (server-side only)
SUPABASE_ANON_KEY=                 # For public-facing operations

# Groq
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

# Replicate (Try-On Engine)
REPLICATE_API_TOKEN=
REPLICATE_VITON_MODEL=            # e.g. cuuupid/idm-vton or equivalent

# OpenAI Whisper (voice transcription)
OPENAI_API_KEY=                   # Used only for Whisper, not GPT

# App
APP_ENV=production                # production | development
BASE_URL=                         # Your Render.com URL
LOG_LEVEL=INFO
```

---

## DATABASE SCHEMA (Supabase)

### Core Tables

```sql
-- TENANTS (one row per seller/client)
CREATE TABLE tenants (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_number_id   TEXT UNIQUE NOT NULL,   -- Meta phone_number_id = tenant key
  business_name     TEXT NOT NULL,
  plan              TEXT NOT NULL DEFAULT 'starter', -- starter | essential | enterprise
  whatsapp_number   TEXT NOT NULL,
  language          TEXT DEFAULT 'en',      -- en | hi | te | ta (vernacular support)
  catalog_enabled   BOOLEAN DEFAULT true,
  active            BOOLEAN DEFAULT true,
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  settings          JSONB DEFAULT '{}'      -- per-tenant LLM prompt overrides etc.
);

-- CUSTOMERS (per-tenant, phone_hash as identifier)
CREATE TABLE customers (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
  phone_hash      TEXT NOT NULL,            -- SHA-256 of customer phone, never raw
  consent_given   BOOLEAN DEFAULT false,
  consent_at      TIMESTAMPTZ,
  language        TEXT DEFAULT 'en',
  skin_tone_code  TEXT,                     -- Monk scale: 1-10, cached after first detection
  last_active     TIMESTAMPTZ DEFAULT NOW(),
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(tenant_id, phone_hash)
);

-- TRYON_JOBS
CREATE TABLE tryon_jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id     UUID REFERENCES customers(id) ON DELETE CASCADE,
  status          TEXT DEFAULT 'pending',   -- pending | processing | completed | failed
  category        TEXT NOT NULL,            -- apparel | jewelry | eyewear | footwear | watch | makeup
  product_ref     TEXT,                     -- catalog product_id or description
  selfie_path     TEXT,                     -- temp Supabase Storage path, TTL 24h
  output_path     TEXT,                     -- try-on result path, TTL 48h
  output_url      TEXT,                     -- signed URL sent to customer
  error_message   TEXT,
  replicate_id    TEXT,                     -- Replicate prediction ID for status polling
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  completed_at    TIMESTAMPTZ,
  deleted_at      TIMESTAMPTZ              -- soft delete for audit trail
);

-- CONSENT_LOG (DPDP audit trail)
CREATE TABLE consent_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID REFERENCES tenants(id),
  phone_hash      TEXT NOT NULL,
  action          TEXT NOT NULL,            -- given | withdrawn | deletion_requested | deleted
  purpose         TEXT DEFAULT 'virtual_tryon',
  ip_hash         TEXT,                     -- hashed if available
  timestamp       TIMESTAMPTZ DEFAULT NOW()
);

-- PROCESSED_MESSAGES (idempotency)
CREATE TABLE processed_messages (
  message_id      TEXT PRIMARY KEY,
  tenant_id       UUID REFERENCES tenants(id),
  processed_at    TIMESTAMPTZ DEFAULT NOW()
);

-- CATALOG_ITEMS (per tenant)
CREATE TABLE catalog_items (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
  product_id      TEXT NOT NULL,
  name            TEXT NOT NULL,
  category        TEXT NOT NULL,
  price           NUMERIC,
  image_url       TEXT NOT NULL,            -- flat-lay or product photo
  tags            TEXT[],                   -- occasion, color, fabric etc.
  active          BOOLEAN DEFAULT true,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(tenant_id, product_id)
);

-- USAGE_TRACKING (plan enforcement)
CREATE TABLE usage_tracking (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
  month           TEXT NOT NULL,            -- YYYY-MM
  tryons_count    INTEGER DEFAULT 0,
  UNIQUE(tenant_id, month)
);
```

### RLS Policies (Critical — All Must Be Enabled)

```sql
-- Every table is scoped to tenant_id
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE tryon_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE catalog_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_tracking ENABLE ROW LEVEL SECURITY;

-- Example policy (repeat for all tables)
CREATE POLICY tenant_isolation ON customers
  USING (tenant_id = current_setting('app.tenant_id')::UUID);
```

> **RULE:** Every Supabase query MUST include `tenant_id` filter. No exceptions. No cross-tenant data leakage.

---

## PLAN FEATURES REGISTRY

```python
# core/constants.py

PLAN_FEATURES = {
    "starter": {
        "monthly_tryon_limit": 1000,
        "categories": ["apparel", "jewelry"],
        "occasion_agent": False,
        "fit_verification": False,
        "voice_support": False,
        "skin_tone_advisory": False,
        "friend_share_loop": False,
        "analytics_dashboard": False,
        "catalog_photoshoot": False,    # flat-lay → model photos
        "languages": ["en"],
        "price_monthly_inr": 10000,
        "price_setup_inr": 25000,
    },
    "essential": {
        "monthly_tryon_limit": 5000,
        "categories": ["apparel", "jewelry", "eyewear", "footwear", "watch", "makeup"],
        "occasion_agent": True,
        "fit_verification": True,
        "voice_support": True,
        "skin_tone_advisory": True,
        "friend_share_loop": True,
        "analytics_dashboard": True,
        "catalog_photoshoot": False,
        "languages": ["en", "hi", "te"],
        "price_monthly_inr": 25000,
        "price_setup_inr": 35000,
    },
    "enterprise": {
        "monthly_tryon_limit": None,    # unlimited
        "categories": ["apparel", "jewelry", "eyewear", "footwear", "watch", "makeup",
                       "kids_wear", "hair_color", "home_decor"],
        "occasion_agent": True,
        "fit_verification": True,
        "voice_support": True,
        "skin_tone_advisory": True,
        "friend_share_loop": True,
        "analytics_dashboard": True,
        "catalog_photoshoot": True,
        "languages": ["en", "hi", "te", "ta", "kn", "mr"],
        "price_monthly_inr": 50000,
        "price_setup_inr": 55000,
    }
}
```

---

## CORE FLOWS — COMPLETE SPECIFICATION

### 1. Webhook Entry Point

```
POST /webhook
  ↓
HMAC signature verification (reject if invalid — return 200 to Meta anyway)
  ↓
Idempotency check (processed_messages table)
  ↓
Tenant resolution (phone_number_id → tenant row)
  ↓
Message type routing:
  - text → intent_router
  - image → image_handler (selfie or product photo)
  - audio → voice_transcription → intent_router
  - interactive (button reply) → button_handler
  ↓
FastAPI BackgroundTask (never block webhook response)
  ↓
Return HTTP 200 immediately (Meta requires < 5s response)
```

> **CRITICAL:** Always return HTTP 200 to Meta webhook even on internal errors. Log errors internally. Never let webhook timeout — Meta will retry and cause duplicate processing.

---

### 2. Intent Router

Uses a single Groq call (fast, cheap) to classify incoming message:

```python
INTENTS = {
    "tryon_single":      # "try this on", sends product image, "how will this look"
    "tryon_occasion":    # "wedding outfit", "office look", "Diwali dress"
    "consent_give":      # "I agree", "yes", "ok" after consent prompt
    "consent_withdraw":  # "delete my data", "remove me", "DELETE"
    "catalog_browse":    # "show me sarees", "what do you have under 2000"
    "fit_check":         # "it arrived, does it fit", post-purchase photo
    "friend_share":      # "share with friend", "get opinion"
    "help":              # "how does this work", "what can you do"
    "greeting":          # "hi", "hello", "namaste"
    "unknown":           # fallback
}
```

System prompt for intent classifier:
```
You are an intent classifier for a WhatsApp virtual try-on bot for Indian fashion boutiques.
Classify the user message into exactly ONE intent from: tryon_single, tryon_occasion,
consent_give, consent_withdraw, catalog_browse, fit_check, friend_share, help, greeting, unknown.
Respond with ONLY the intent string. No explanation.
```

---

### 3. Consent Flow (DPDP Compliant)

**Trigger:** Any user who has not given consent yet (customers.consent_given = false)

**Flow:**
```
1. Bot sends consent message (in user's language):
   "Namaste! 👗 ZukoLabs Virtual Try-On ke liye welcome hai!
   
   Aapki photo try-on generate karne ke liye use hogi.
   ✅ Photo sirf try-on ke liye use hogi
   ✅ Processing ke baad 24 ghante mein delete ho jayegi  
   ✅ Kabhi bhi DELETE likhkar apna data remove kar sakte ho
   
   Privacy Policy: [link]
   
   Agree karne ke liye AGREE bhejo 👇"

2. User replies AGREE → 
   - customers.consent_given = true
   - customers.consent_at = NOW()
   - consent_log INSERT (action: 'given')
   - Proceed to requested flow

3. User declines / ignores →
   - Do not process any photo
   - Send: "No problem! Jab bhi ready ho, AGREE bhejo."
```

**Rules:**
- Consent message sent ONCE per customer per tenant
- Re-consent required if customer hasn't interacted in 12 months
- Consent must be explicit ("AGREE") — not implied by sending a photo
- All consent_log records retained for 7 years (legal requirement)

---

### 4. Core Try-On Flow (Chatbot — 80% of traffic)

```
State machine per customer session (stored in Supabase or in-memory dict):

STATE: IDLE
  → User sends product image or product reference
  → Transition to: AWAITING_SELFIE
  → Bot: "Perfect! Ab apni ek clear selfie bhejo 📸 
          (full face, good lighting, plain background best hai)"

STATE: AWAITING_SELFIE  
  → User sends selfie
  → Validate: is it a face photo? (basic CV check)
  → If valid: Transition to PROCESSING
  → If invalid: "Yeh selfie nahi lag rahi. Ek aur try karo? 😊"

STATE: PROCESSING
  → Bot sends: "Generating your try-on... ✨ (20-30 seconds)"
  → BackgroundTask: call tryon_engine.generate()
  → On completion: send output image
  → Transition to POST_TRYON

STATE: POST_TRYON
  → Bot sends try-on image
  → Bot sends quick reply buttons:
    [Try Another] [Share with Friend*] [View Catalog] [Buy Now]
    (* only if plan has friend_share_loop)
  → Check plan limit before each job (usage_tracking)
  → Transition to IDLE
```

**Try-On Engine Wrapper:**
```python
# services/tryon_engine.py
async def generate(selfie_url: str, product_url: str, category: str) -> str:
    """
    Returns output image URL.
    Uses Replicate IDM-VTON for apparel.
    Uses MediaPipe + asset overlay for jewelry/eyewear/watch.
    Raises TryOnError on failure.
    """
```

**Category → Engine mapping:**
```python
CATEGORY_ENGINE = {
    "apparel":    "replicate_viton",      # IDM-VTON diffusion model
    "kids_wear":  "replicate_viton",
    "makeup":     "replicate_makeup",     # color overlay model
    "jewelry":    "mediapipe_ar",         # face/hand landmark + 3D overlay
    "eyewear":    "mediapipe_ar",
    "watch":      "mediapipe_ar",         # wrist landmark
    "footwear":   "replicate_viton",      # foot try-on variant
    "hair_color": "replicate_hair",       # hair segmentation + recolor
    "home_decor": "arcore_room",          # room scan (future)
}
```

---

### 5. Occasion Agent (Essential/Enterprise Only)

Mini-agent with max 3 tool calls. Uses Groq tool-calling.

**Tools available:**
```python
tools = [
    {
        "name": "search_catalog",
        "description": "Search seller's catalog by occasion, category, budget, color",
        "parameters": {
            "occasion": "str",       # wedding, office, casual, festival, party
            "budget_max": "int",     # INR
            "category": "str",
            "color_preference": "str"
        }
    },
    {
        "name": "check_skin_tone_compatibility",
        "description": "Given a skin tone code and garment colors, return compatibility score and recommendation",
        "parameters": {
            "skin_tone_code": "str", # Monk scale 1-10
            "garment_colors": "list[str]"
        }
    },
    {
        "name": "generate_tryon",
        "description": "Generate try-on for a specific product",
        "parameters": {
            "product_id": "str",
            "selfie_url": "str"
        }
    }
]
```

**Agent System Prompt:**
```
You are a personal stylist assistant for an Indian fashion boutique's WhatsApp bot.
The customer has described their occasion and preferences.
Use the available tools to: 1) find 2-3 relevant products, 2) check color compatibility with their skin tone if known, 3) generate a try-on for the best match.
Be conversational, warm, and use a mix of Hindi/English (Hinglish) if the customer used Hindi.
Maximum 3 tool calls. Always end by presenting the try-on result with a buying option.
Never suggest products outside the seller's catalog.
```

---

### 6. Skin Tone Advisory

Runs once per customer, cached in `customers.skin_tone_code`.

```python
# services/skin_tone.py
async def detect_skin_tone(selfie_url: str) -> str:
    """
    Downloads selfie, detects face region using MediaPipe,
    samples skin pixels from cheek/forehead area,
    maps to Monk Skin Tone Scale (1-10).
    Returns: "MST-3", "MST-7" etc.
    Deletes local copy after detection.
    """
```

**Color compatibility matrix (Indian context):**
```python
SKIN_TONE_COLORS = {
    "MST-1": {"flattering": ["pastels", "coral", "peach"], "avoid": ["neon", "very pale yellow"]},
    "MST-2": {"flattering": ["earth tones", "warm red", "gold"], "avoid": []},
    "MST-3": {"flattering": ["jewel tones", "burgundy", "forest green"], "avoid": ["beige"]},
    "MST-4": {"flattering": ["bright colors", "royal blue", "magenta"], "avoid": []},
    "MST-5": {"flattering": ["vibrant", "orange", "electric blue"], "avoid": []},
    # ... continues to MST-10
}
```

---

### 7. Friend Share Loop (Essential/Enterprise Only)

```
After try-on delivered:
  ↓
Bot: "Apni family/friend ka opinion lena chahte ho? 
      SHARE bhejo aur unka WhatsApp number dena"
  ↓
Customer sends friend's number
  ↓
System sends try-on image to friend with message:
  "[Customer Name] ne yeh saree try kiya. Kaisa lag raha hai? 
   👍 YES ya 👎 NO reply karo"
  ↓
Friend replies YES/NO
  ↓
System forwards friend's response to customer:
  "Tumhare friend ne 👍 bola! Ready to order? BUY bhejo"
  ↓
If BUY: send seller's payment link / catalog link
```

> **Privacy note:** Friend's number used only for this single message thread. Not stored in database. Consent notice sent with the message.

---

### 8. Post-Purchase Fit Verification (Essential/Enterprise Only)

**Trigger:** Automated WhatsApp message sent 2 days after order marked delivered.

```
Bot: "Aapka order aa gaya! 📦 
      Wearing karke ek photo bhejo — hum check karenge fit perfect hai ya nahi 😊"
  ↓
Customer sends wearing photo
  ↓
Groq vision analysis:
  - Is garment fitting well? (too tight / too loose / good)
  - Are there obvious size issues?
  ↓
If GOOD_FIT:
  Bot: "Perfect fit lag raha hai! 🎉 Yeh tips try karo: [styling suggestions]"
  → Upsell: "Matching dupatta dekhna hai? MATCH bhejo"

If SIZE_ISSUE:
  Bot: "Haan, size thoda [large/small] lag raha hai. 
       Return ke liye RETURN bhejo — hum process kar denge"
  → Trigger seller's return flow

If UNCLEAR:
  Bot: "Thoda better photo bhejo? Good lighting mein, full length"
```

---

### 9. Deletion Flow (DPDP Right to Erasure)

**Triggers:** "DELETE", "delete my data", "mujhe hatao", "remove me"

```python
async def handle_deletion(phone_hash: str, tenant_id: str):
    # 1. Delete all tryon_jobs for this customer (raw selfies already auto-deleted)
    # 2. Delete output images from Supabase Storage
    # 3. Set customers.consent_given = false, last_active = null
    # 4. Insert consent_log record (action: 'deleted')
    # 5. Keep consent_log itself for 7 years (legal requirement)
    # 6. Send confirmation:
    #    "Aapka sara data delete ho gaya. ✅
    #     Agar dobara use karna ho, AGREE bhejke restart kar sakte ho."
```

**Deadline:** Must complete within 90 days per DPDP Rules. Target: immediate (under 5 seconds).

---

### 10. Voice / Vernacular Flow (Essential/Enterprise Only)

```
Customer sends voice note in Hindi/Telugu/Tamil
  ↓
services/voice_transcription.py → OpenAI Whisper API
  ↓
Transcribed text → intent_router (same pipeline as text)
  ↓
All responses sent in customer's detected language
  (language detected from first message and stored in customers.language)
```

**Language response templates stored per tenant in `tenants.settings`:**
```json
{
  "language_templates": {
    "te": {
      "consent": "స్వాగతం! మీ ఫోటో try-on కోసం మాత్రమే వాడతాం...",
      "awaiting_selfie": "మీ selfie పంపండి 📸",
      "processing": "మీ look generate అవుతోంది... ✨"
    },
    "hi": {
      "consent": "Namaste! Aapki photo sirf try-on ke liye...",
      "awaiting_selfie": "Apni selfie bhejo 📸",
      "processing": "Aapka look ban raha hai... ✨"
    }
  }
}
```

---

## GROQ CLIENT — RELIABILITY REQUIREMENTS

```python
# services/groq_client.py

GROQ_CONFIG = {
    "model": "llama-3.3-70b-versatile",
    "max_tokens": 150,          # Keep low for intent classification
    "temperature": 0.1,         # Low for deterministic intent routing
    "timeout": 8,               # Seconds before timeout
}

RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay": 1.0,          # seconds
    "max_delay": 10.0,
    "backoff_multiplier": 2.0,
    "retry_on": [429, 500, 502, 503, 504],
}

# Dead letter queue for failed LLM calls
DLQ_TABLE = "failed_llm_calls"  # Supabase table for manual review
```

**Rules:**
- Intent classification: max_tokens=50, temperature=0.0 — pure routing, no creativity needed
- Occasion agent: max_tokens=500, temperature=0.3
- Fit verification analysis: max_tokens=200, temperature=0.1
- Always set a system prompt that ends with: `"Respond in the user's language: {language}"`

---

## REPLICATE VITON ENGINE — RELIABILITY REQUIREMENTS

```python
# services/tryon_engine.py

REPLICATE_CONFIG = {
    "model": "cuuupid/idm-vton",    # Update with latest stable version
    "timeout_poll": 60,              # Max seconds to wait for result
    "poll_interval": 3,              # Check every 3 seconds
    "max_image_size_mb": 5,          # Resize before upload if larger
    "output_quality": 85,            # JPEG quality for output
}

FALLBACK_BEHAVIOR = {
    # If Replicate fails after retries:
    "send_message": "Try-on abhi available nahi hai. 2 minutes mein dobara try karo 🙏",
    "log_to_dlq": True,
    "alert_seller": False,           # Don't spam seller on individual failures
}
```

**Image preprocessing before sending to Replicate:**
```python
async def preprocess_image(image_bytes: bytes) -> bytes:
    # 1. Resize to max 768x1024 (VITON optimal)
    # 2. Convert to RGB (strip alpha channel)
    # 3. Compress to under 5MB
    # 4. Return processed bytes
    # Never save to disk — process in memory only
```

---

## WHATSAPP SERVICE — MESSAGE TEMPLATES

All messages must be under 1024 characters. Use emoji sparingly but consistently.

```python
# services/whatsapp.py

MESSAGES = {
    "greeting": "Namaste! 👋 Hum aapke virtual try-on assistant hain. Koi bhi outfit try karna ho, photo bhejo!",
    
    "awaiting_selfie": "📸 Ab apni selfie bhejo!\nTips:\n• Achhi lighting\n• Clear face\n• Plain background\n• Front-facing",
    
    "processing": "✨ Aapka look generate ho raha hai...\n(20-30 seconds)",
    
    "tryon_complete": "🎉 Yeh raha aapka look!\n\n",  # image sent separately
    
    "plan_limit_reached": "Aaj ke try-ons khatam ho gaye 😊 Kal dobara try karo, ya {seller_name} se baat karo upgrade ke liye.",
    
    "invalid_selfie": "Yeh selfie clear nahi hai. Ek aur try karo? 😊",
    
    "help": "Main kya kar sakta hoon:\n👗 Outfit try-on: product photo bhejo\n💍 Jewellery try-on\n🗑️ Data delete: DELETE bhejo\n🛍️ Catalog: CATALOG bhejo",
    
    "unknown_intent": "Samajh nahi aaya 😅 'help' bhejo options dekhne ke liye",
}
```

**Interactive button template (Post Try-On):**
```python
POST_TRYON_BUTTONS = {
    "type": "interactive",
    "interactive": {
        "type": "button",
        "body": {"text": "Kaisa laga? 👆"},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "try_another", "title": "Try Another 👗"}},
                {"type": "reply", "reply": {"id": "view_catalog", "title": "View Catalog 🛍️"}},
                {"type": "reply", "reply": {"id": "buy_now", "title": "Buy Now 💳"}},
            ]
        }
    }
}
```

---

## PERFORMANCE REQUIREMENTS

| Metric | Target | Maximum |
|--------|--------|---------|
| Webhook → 200 response | < 500ms | 5s (Meta limit) |
| Intent classification (Groq) | < 2s | 4s |
| WhatsApp message send | < 1s | 3s |
| Try-on generation (Replicate) | 20-30s | 60s |
| Consent flow complete | < 5s | 10s |
| Data deletion | < 5s | 90 days (DPDP max) |

**All flows must run in FastAPI BackgroundTasks.** Never block the webhook handler.

---

## DPDP ACT COMPLIANCE CHECKLIST

Every release must verify:

- [ ] **Consent before photo processing** — No selfie processed without explicit "AGREE"
- [ ] **Purpose limitation** — Photos used only for try-on generation, never for training
- [ ] **Data minimisation** — Only collect phone_hash (not raw number), selfie (temp), consent timestamp
- [ ] **Raw selfie deletion** — Deleted from memory immediately after Replicate call completes
- [ ] **Output image TTL** — 48-hour auto-expiry on Supabase Storage
- [ ] **Deletion on demand** — DELETE command wipes all records within 5 seconds
- [ ] **Consent log retention** — consent_log records kept for 7 years (never deleted)
- [ ] **Breach notification** — 72-hour notification process documented
- [ ] **No cross-tenant data** — RLS policies verified on every Supabase query
- [ ] **Privacy policy URL** — Live, accessible, plain-language, linked in consent message
- [ ] **Children's data** — No try-on for users who identify as under 18 (block flow)
- [ ] **No phone number storage** — Always hash with SHA-256 before storing

---

## MULTI-TENANCY RULES (Non-Negotiable)

1. **Tenant resolved at webhook entry** using `phone_number_id` from Meta payload
2. **Set Supabase context** before every query: `SET LOCAL app.tenant_id = '{tenant_id}'`
3. **Every query includes explicit `tenant_id` filter** in addition to RLS
4. **Plan limits enforced** in `middleware/rate_limiter.py` before every try-on job
5. **Tenant settings override global defaults** — language, prompt, catalog, features
6. **No shared state** between tenants — separate catalog, separate customers, separate usage

```python
# middleware/tenant_resolver.py
async def resolve_tenant(phone_number_id: str) -> Tenant:
    tenant = await supabase
        .table("tenants")
        .select("*")
        .eq("phone_number_id", phone_number_id)
        .eq("active", True)
        .single()
        .execute()
    if not tenant.data:
        raise TenantNotFoundError(f"No active tenant for {phone_number_id}")
    return Tenant(**tenant.data)
```

---

## ERROR HANDLING PATTERNS

```python
# All service calls follow this pattern:

try:
    result = await service_call()
except RateLimitError:
    await asyncio.sleep(backoff_delay)
    # retry with exponential backoff
except TimeoutError:
    await send_whatsapp_message(customer, MESSAGES["processing_delay"])
    await log_to_dlq(job_id, "timeout")
except ReplicateError as e:
    await send_whatsapp_message(customer, MESSAGES["tryon_failed"])
    await log_error(e, job_id)
except Exception as e:
    # Never crash the webhook handler
    await log_error(e, job_id)
    # Send friendly fallback to user
    await send_whatsapp_message(customer, MESSAGES["unknown_error"])
```

**Dead Letter Queue pattern (same as MediAssist):**
```sql
CREATE TABLE dead_letter_queue (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type    TEXT,               -- tryon | llm_call | whatsapp_send
  payload     JSONB,
  error       TEXT,
  tenant_id   UUID,
  retry_count INTEGER DEFAULT 0,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);
```

---

## IDEMPOTENCY (Critical for WhatsApp)

Meta may deliver the same webhook multiple times. Every message must be processed exactly once.

```python
# middleware/idempotency.py
async def is_duplicate(message_id: str) -> bool:
    result = await supabase
        .table("processed_messages")
        .select("message_id")
        .eq("message_id", message_id)
        .execute()
    if result.data:
        return True
    # Insert immediately (before processing)
    await supabase.table("processed_messages").insert({
        "message_id": message_id,
        "processed_at": datetime.utcnow().isoformat()
    }).execute()
    return False
```

---

## SELLER ADMIN DASHBOARD (API Routes)

```
GET  /admin/tenants/{tenant_id}/stats          # Usage this month, tryons count
GET  /admin/tenants/{tenant_id}/catalog         # List catalog items
POST /admin/tenants/{tenant_id}/catalog         # Add catalog item
PUT  /admin/tenants/{tenant_id}/catalog/{id}    # Update item
DEL  /admin/tenants/{tenant_id}/catalog/{id}    # Remove item
POST /admin/tenants/{tenant_id}/catalog/bulk    # Bulk upload via CSV
GET  /admin/tenants/{tenant_id}/customers       # Anonymised customer stats
POST /admin/onboard                             # New tenant setup
```

**Bulk catalog upload (flat-lay → model photos pipeline):**
```
POST /admin/tenants/{tenant_id}/catalog/photoshoot
  Body: { product_ids: [...] }
  → Pulls flat-lay images from catalog
  → Sends to Replicate image-to-model pipeline
  → Returns model photos for each product
  → Updates catalog_items.image_url
  (Enterprise plan only)
```

---

## DEPLOYMENT (Render.com)

```yaml
# render.yaml
services:
  - type: web
    name: zukolabs-vto
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT --workers 4
    healthCheckPath: /health
    autoDeploy: true
    envVars:
      - key: APP_ENV
        value: production
```

**Render settings:**
- Instance type: Standard (1 CPU, 2GB RAM) — upgrade to Pro when > 20 tenants
- Auto-deploy: on push to `main` branch only
- Health check: `/health` returns `{"status": "ok", "tenants": N}`

---

## TESTING REQUIREMENTS

Before any production deployment:

```bash
# Run all tests
pytest tests/ -v

# Specific suites
pytest tests/test_dpdp_compliance.py -v    # DPDP rules verification
pytest tests/test_flows.py -v              # All chat flows
pytest tests/test_tryon_engine.py -v       # Try-on generation
```

**Mandatory test cases:**
- [ ] Consent flow blocks processing until AGREE received
- [ ] DELETE command removes all customer data within 5 seconds
- [ ] Cross-tenant isolation: tenant A cannot see tenant B's customers
- [ ] Plan limit enforcement: Starter tenant blocked at 1000 try-ons/month
- [ ] Idempotency: same message_id processed only once
- [ ] Webhook returns 200 even when internal error occurs
- [ ] Groq retry logic triggers on 429 response
- [ ] Replicate timeout sends fallback message to user

---

## ADDING A NEW TENANT (Onboarding Checklist)

1. [ ] Insert row into `tenants` table with their `phone_number_id`
2. [ ] Set `plan`, `language`, `business_name`
3. [ ] Configure Meta App with their WhatsApp Business number
4. [ ] Upload initial catalog via `/admin/onboard` or bulk CSV
5. [ ] Set per-tenant system prompt in `tenants.settings.llm_prompt`
6. [ ] Send test message to verify webhook routing works
7. [ ] Confirm DPDP consent message renders correctly in their language
8. [ ] Zero redeployment required — new tenant = new DB row only

---

## COMMON PITFALLS — DO NOT DO THESE

- ❌ **Never store raw phone numbers** — always SHA-256 hash before DB insert
- ❌ **Never block the webhook thread** — all processing in BackgroundTasks
- ❌ **Never process a photo without checking consent_given = true first**
- ❌ **Never query Supabase without tenant_id filter**
- ❌ **Never let Replicate/Groq errors crash the webhook handler**
- ❌ **Never call Groq more than 3 times per user message** (cost + latency)
- ❌ **Never store selfies beyond the inference call** (DPDP violation)
- ❌ **Never use bundled or pre-checked consent** (DPDP violation)
- ❌ **Never expose SUPABASE_SERVICE_KEY to client-side code**
- ❌ **Never deploy to production from any branch other than `main`**

---

## QUICK REFERENCE — KEY FILES

| Task | File |
|------|------|
| Handle incoming WhatsApp message | `api/webhook.py` |
| Route message to correct flow | `flows/intent_router.py` |
| Generate try-on image | `services/tryon_engine.py` |
| DPDP consent + deletion | `flows/consent_flow.py`, `flows/deletion_flow.py` |
| Groq LLM calls | `services/groq_client.py` |
| Plan feature checking | `core/constants.py` → `PLAN_FEATURES` |
| Multi-tenant resolution | `middleware/tenant_resolver.py` |
| Send WhatsApp messages | `services/whatsapp.py` |
| Skin tone detection | `services/skin_tone.py` |
| Voice transcription | `services/voice_transcription.py` |

---

*Built by ZukoLabs · zukolabs14@gmail.com · Visakhapatnam, India*
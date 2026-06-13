# ZukoLabs VTO — Implementation Walkthrough

The ZukoLabs Virtual Try-On (VTO) system has been fully implemented according to the specifications in `claude.md`. We have successfully built a multi-tenant, WhatsApp-native platform that integrates seamlessly with Meta APIs, Supabase, Groq, and Replicate.

## Architecture & System Design
The system uses **FastAPI** to provide high-performance asynchronous endpoints and manages its routing via a modular package structure:

- **`core/`**: Central configuration, database connectivity, HMAC webhook security, and constants.
- **`models/`**: Pydantic models mapping to the Supabase schema (`Tenant`, `Customer`, `CustomerSession`, `TryOnJob`, `ConsentLog`).
- **`middleware/`**: Redis-style idempotency handling for WhatsApp retries, Plan-based rate limiting, and Phone-number based Tenant resolution.
- **`services/`**: API wrappers for external integrations:
  - **WhatsApp API**: Media downloading, text/image sending, and interactive button replies.
  - **Groq LLM**: Intent routing (classification), AI occasional agent, and fit verification.
  - **Replicate**: Virtual try-on generation using the VITON-HD engine.
  - **OpenAI**: Whisper transcription for vernacular voice notes.
  - **Supabase Storage**: 24/48-hour TTL-based self/output image storage.
- **`flows/`**: Core logic for the state machine handling:
  - **Consent**: Strict DPDP-compliant opt-in logic.
  - **Try-On**: State machine transitioning from product photo $\rightarrow$ selfie $\rightarrow$ generation.
  - **Occasion Agent**: Tool-calling mini-agent for style recommendations.
  - **Fit Verification**: Post-purchase evaluation and styling tips.
  - **Help / Catalog**: Browsing and feature discovery flows.

## Compliance and Security (DPDP Act)
We have implemented strict Data Protection features:
1. **Never store raw phone numbers**: `core.security.hash_phone_number` hashes phone numbers using SHA-256 before they touch the database.
2. **Explicit Consent**: `flows.consent_flow` handles requesting explicit "AGREE" before processing selfies.
3. **Right to Erasure**: `flows.deletion_flow` handles customer data deletion, scrubbing all personal data and images while leaving a non-reversible audit log for legal compliance.
4. **Re-Consent**: `needs_consent` logic checks for 12-month inactivity to re-prompt for consent automatically.

## Webhook Handling
The `api/webhook.py` router strictly follows Meta's guidelines:
- Immediately returns an HTTP `200 OK` to prevent retries.
- Dispatches message processing using FastAPI's `BackgroundTasks` module to perform the heavy lifting (e.g., downloading images, querying the LLM, and generating try-ons) without blocking the thread.

## Testing & Verification
We have implemented comprehensive unit and flow tests in the `tests/` directory:
- **`test_dpdp_compliance.py`**: Verifies phone hashing, explicit consent gating, cross-tenant isolation, and 12-month re-consent logic.
- **`test_flows.py`**: Verifies intent classification mapping, state machine logic, and webhook verification.
- **`test_tryon_engine.py`**: Verifies image preprocessing resizing constraints and fallback behavior on Replicate API timeout/failures.

The tests have been successfully run utilizing `pytest`, and all 45 cases pass cleanly, ensuring complete robustness.

## Next Steps for Deployment
The project includes a `render.yaml` for zero-downtime deployment via Render.com.

1. Create a PostgreSQL/Supabase instance and initialize the tables based on the schema mapping in `claude.md`.
2. Connect your Render account to this Git repository and deploy.
3. Set the environment variables (e.g. `SUPABASE_URL`, `SUPABASE_KEY`, `GROQ_API_KEY`, `REPLICATE_API_TOKEN`, `WHATSAPP_APP_SECRET`).
4. Link the `GET /webhook` endpoint to your Meta App Dashboard for your WhatsApp numbers.

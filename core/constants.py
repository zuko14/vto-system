"""
ZukoLabs VTO — Constants & Configuration Registry

Plan features, category-engine mapping, skin tone color matrix,
intent definitions, and message templates.
"""

from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# INTENT DEFINITIONS
# ═══════════════════════════════════════════════════════════════

class Intent(str, Enum):
    """All recognized user intents for the intent router."""
    TRYON_SINGLE = "tryon_single"
    TRYON_OCCASION = "tryon_occasion"
    CONSENT_GIVE = "consent_give"
    CONSENT_WITHDRAW = "consent_withdraw"
    CATALOG_BROWSE = "catalog_browse"
    FIT_CHECK = "fit_check"
    FRIEND_SHARE = "friend_share"
    HELP = "help"
    GREETING = "greeting"
    UNKNOWN = "unknown"


class SessionState(str, Enum):
    """Customer session states for the try-on flow state machine."""
    IDLE = "idle"
    AWAITING_SELFIE = "awaiting_selfie"
    PROCESSING = "processing"
    POST_TRYON = "post_tryon"
    AWAITING_CONSENT = "awaiting_consent"
    AWAITING_FRIEND_NUMBER = "awaiting_friend_number"


class TryOnStatus(str, Enum):
    """Status of a try-on job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ConsentAction(str, Enum):
    """Consent log actions for DPDP audit trail."""
    GIVEN = "given"
    WITHDRAWN = "withdrawn"
    DELETION_REQUESTED = "deletion_requested"
    DELETED = "deleted"


class TryOnCategory(str, Enum):
    """Supported try-on categories."""
    APPAREL = "apparel"
    JEWELRY = "jewelry"
    EYEWEAR = "eyewear"
    FOOTWEAR = "footwear"
    WATCH = "watch"
    MAKEUP = "makeup"
    KIDS_WEAR = "kids_wear"
    HAIR_COLOR = "hair_color"
    HOME_DECOR = "home_decor"


# ═══════════════════════════════════════════════════════════════
# PLAN FEATURES REGISTRY
# ═══════════════════════════════════════════════════════════════

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
        "catalog_photoshoot": False,
        "languages": ["en"],
        "price_monthly_inr": 10000,
        "price_setup_inr": 25000,
    },
    "essential": {
        "monthly_tryon_limit": 5000,
        "categories": [
            "apparel", "jewelry", "eyewear",
            "footwear", "watch", "makeup",
        ],
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
        "monthly_tryon_limit": None,  # unlimited
        "categories": [
            "apparel", "jewelry", "eyewear", "footwear",
            "watch", "makeup", "kids_wear", "hair_color",
            "home_decor",
        ],
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
    },
}


# ═══════════════════════════════════════════════════════════════
# CATEGORY → ENGINE MAPPING
# ═══════════════════════════════════════════════════════════════

CATEGORY_ENGINE = {
    "apparel": "replicate_viton",
    "kids_wear": "replicate_viton",
    "makeup": "replicate_makeup",
    "jewelry": "mediapipe_ar",
    "eyewear": "mediapipe_ar",
    "watch": "mediapipe_ar",
    "footwear": "replicate_viton",
    "hair_color": "replicate_hair",
    "home_decor": "arcore_room",
}


# ═══════════════════════════════════════════════════════════════
# SKIN TONE COLOR COMPATIBILITY (Monk Skin Tone Scale)
# ═══════════════════════════════════════════════════════════════

SKIN_TONE_COLORS = {
    "MST-1": {
        "flattering": ["pastels", "coral", "peach", "soft pink", "baby blue"],
        "avoid": ["neon", "very pale yellow"],
    },
    "MST-2": {
        "flattering": ["earth tones", "warm red", "gold", "olive green"],
        "avoid": ["stark white"],
    },
    "MST-3": {
        "flattering": ["jewel tones", "burgundy", "forest green", "teal"],
        "avoid": ["beige", "nude"],
    },
    "MST-4": {
        "flattering": ["bright colors", "royal blue", "magenta", "emerald"],
        "avoid": ["washed-out pastels"],
    },
    "MST-5": {
        "flattering": ["vibrant", "orange", "electric blue", "fuchsia"],
        "avoid": ["muted browns"],
    },
    "MST-6": {
        "flattering": ["rich jewel tones", "cobalt", "deep purple", "gold"],
        "avoid": ["pale khaki"],
    },
    "MST-7": {
        "flattering": ["bright yellow", "coral", "turquoise", "white"],
        "avoid": ["dark navy alone"],
    },
    "MST-8": {
        "flattering": ["bright white", "hot pink", "electric green", "red"],
        "avoid": ["dark brown", "charcoal"],
    },
    "MST-9": {
        "flattering": ["bold white", "bright red", "royal purple", "gold"],
        "avoid": ["very dark muted tones"],
    },
    "MST-10": {
        "flattering": ["stark white", "bold yellow", "vibrant orange", "silver"],
        "avoid": ["very dark colors near skin tone"],
    },
}


# ═══════════════════════════════════════════════════════════════
# GROQ CLIENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════

GROQ_CONFIG = {
    "model": "llama-3.3-70b-versatile",
    "max_tokens": 150,
    "temperature": 0.1,
    "timeout": 8,
}

RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay": 1.0,
    "max_delay": 10.0,
    "backoff_multiplier": 2.0,
    "retry_on": [429, 500, 502, 503, 504],
}


# ═══════════════════════════════════════════════════════════════
# REPLICATE VITON CONFIGURATION
# ═══════════════════════════════════════════════════════════════

REPLICATE_CONFIG = {
    "model": "cuuupid/idm-vton",
    "timeout_poll": 60,
    "poll_interval": 3,
    "max_image_size_mb": 5,
    "output_quality": 85,
}

FALLBACK_BEHAVIOR = {
    "send_message": (
        "Try-on abhi available nahi hai. "
        "2 minutes mein dobara try karo 🙏"
    ),
    "log_to_dlq": True,
    "alert_seller": False,
}


# ═══════════════════════════════════════════════════════════════
# MESSAGE TEMPLATES
# ═══════════════════════════════════════════════════════════════

MESSAGES = {
    "greeting": (
        "Namaste! 👋 Hum aapke virtual try-on assistant hain. "
        "Koi bhi outfit try karna ho, photo bhejo!"
    ),
    "awaiting_selfie": (
        "📸 Ab apni selfie bhejo!\n"
        "Tips:\n"
        "• Achhi lighting\n"
        "• Clear face\n"
        "• Plain background\n"
        "• Front-facing"
    ),
    "processing": "✨ Aapka look generate ho raha hai...\n(20-30 seconds)",
    "tryon_complete": "🎉 Yeh raha aapka look!\n\n",
    "plan_limit_reached": (
        "Aaj ke try-ons khatam ho gaye 😊 "
        "Kal dobara try karo, ya {seller_name} se baat karo upgrade ke liye."
    ),
    "invalid_selfie": "Yeh selfie clear nahi hai. Ek aur try karo? 😊",
    "help": (
        "Main kya kar sakta hoon:\n"
        "👗 Outfit try-on: product photo bhejo\n"
        "💍 Jewellery try-on\n"
        "🗑️ Data delete: DELETE bhejo\n"
        "🛍️ Catalog: CATALOG bhejo"
    ),
    "unknown_intent": "Samajh nahi aaya 😅 'help' bhejo options dekhne ke liye",
    "tryon_failed": (
        "Try-on abhi available nahi hai. "
        "2 minutes mein dobara try karo 🙏"
    ),
    "processing_delay": (
        "Thoda time lag raha hai... ⏳ "
        "Please wait, hum koshish kar rahe hain."
    ),
    "unknown_error": (
        "Kuch galat ho gaya 😔 "
        "Please dobara try karo ya 'help' bhejo."
    ),
    "deletion_complete": (
        "Aapka sara data delete ho gaya. ✅\n"
        "Agar dobara use karna ho, AGREE bhejke restart kar sakte ho."
    ),
    "consent_declined": "No problem! Jab bhi ready ho, AGREE bhejo.",
}

# Consent message template (supports language substitution)
CONSENT_TEMPLATES = {
    "en": (
        "Welcome! 👗 ZukoLabs Virtual Try-On!\n\n"
        "Your photo will be used only for try-on generation.\n"
        "✅ Photo used only for try-on\n"
        "✅ Deleted within 24 hours after processing\n"
        "✅ Type DELETE anytime to remove your data\n\n"
        "Privacy Policy: {privacy_url}\n\n"
        "Send AGREE to continue 👇"
    ),
    "hi": (
        "Namaste! 👗 ZukoLabs Virtual Try-On ke liye welcome hai!\n\n"
        "Aapki photo try-on generate karne ke liye use hogi.\n"
        "✅ Photo sirf try-on ke liye use hogi\n"
        "✅ Processing ke baad 24 ghante mein delete ho jayegi\n"
        "✅ Kabhi bhi DELETE likhkar apna data remove kar sakte ho\n\n"
        "Privacy Policy: {privacy_url}\n\n"
        "Agree karne ke liye AGREE bhejo 👇"
    ),
    "te": (
        "స్వాగతం! 👗 ZukoLabs Virtual Try-On!\n\n"
        "మీ ఫోటో try-on కోసం మాత్రమే వాడతాం.\n"
        "✅ ఫోటో try-on కోసం మాత్రమే\n"
        "✅ 24 గంటల్లో delete అవుతుంది\n"
        "✅ ఎప్పుడైనా DELETE టైప్ చేసి data తొలగించవచ్చు\n\n"
        "Privacy Policy: {privacy_url}\n\n"
        "AGREE పంపండి 👇"
    ),
    "ta": (
        "வரவேற்கிறோம்! 👗 ZukoLabs Virtual Try-On!\n\n"
        "உங்கள் புகைப்படம் try-on உருவாக்க மட்டுமே பயன்படுத்தப்படும்.\n"
        "✅ புகைப்படம் try-on மட்டுமே\n"
        "✅ 24 மணி நேரத்தில் நீக்கப்படும்\n"
        "✅ எப்போது வேண்டுமானாலும் DELETE தட்டச்சு செய்யுங்கள்\n\n"
        "Privacy Policy: {privacy_url}\n\n"
        "AGREE அனுப்புங்கள் 👇"
    ),
}


# ═══════════════════════════════════════════════════════════════
# POST TRY-ON INTERACTIVE BUTTONS (WhatsApp)
# ═══════════════════════════════════════════════════════════════

POST_TRYON_BUTTONS = {
    "type": "interactive",
    "interactive": {
        "type": "button",
        "body": {"text": "Kaisa laga? 👆"},
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {"id": "try_another", "title": "Try Another 👗"},
                },
                {
                    "type": "reply",
                    "reply": {"id": "view_catalog", "title": "View Catalog 🛍️"},
                },
                {
                    "type": "reply",
                    "reply": {"id": "buy_now", "title": "Buy Now 💳"},
                },
            ]
        },
    },
}

# Friend share button (only for plans with friend_share_loop)
FRIEND_SHARE_BUTTONS = {
    "type": "interactive",
    "interactive": {
        "type": "button",
        "body": {"text": "Kaisa laga? 👆"},
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {"id": "try_another", "title": "Try Another 👗"},
                },
                {
                    "type": "reply",
                    "reply": {"id": "share_friend", "title": "Share 👫"},
                },
                {
                    "type": "reply",
                    "reply": {"id": "buy_now", "title": "Buy Now 💳"},
                },
            ]
        },
    },
}


# ═══════════════════════════════════════════════════════════════
# INTENT CLASSIFIER SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════

INTENT_CLASSIFIER_PROMPT = (
    "You are an intent classifier for a WhatsApp virtual try-on bot for "
    "Indian fashion boutiques.\n"
    "Classify the user message into exactly ONE intent from: "
    "tryon_single, tryon_occasion, consent_give, consent_withdraw, "
    "catalog_browse, fit_check, friend_share, help, greeting, unknown.\n"
    "Respond with ONLY the intent string. No explanation."
)

OCCASION_AGENT_SYSTEM_PROMPT = (
    "You are a personal stylist assistant for an Indian fashion boutique's "
    "WhatsApp bot.\n"
    "The customer has described their occasion and preferences.\n"
    "Use the available tools to: 1) find 2-3 relevant products, "
    "2) check color compatibility with their skin tone if known, "
    "3) generate a try-on for the best match.\n"
    "Be conversational, warm, and use a mix of Hindi/English (Hinglish) "
    "if the customer used Hindi.\n"
    "Maximum 3 tool calls. Always end by presenting the try-on result "
    "with a buying option.\n"
    "Never suggest products outside the seller's catalog.\n"
    "Respond in the user's language: {language}"
)


def get_plan_features(plan: str) -> dict:
    """Get features for a specific plan. Defaults to starter if unknown."""
    return PLAN_FEATURES.get(plan, PLAN_FEATURES["starter"])


def is_feature_enabled(plan: str, feature: str) -> bool:
    """Check if a specific feature is enabled for a plan."""
    features = get_plan_features(plan)
    return features.get(feature, False)


def get_monthly_limit(plan: str) -> Optional[int]:
    """Get monthly try-on limit for a plan. None = unlimited."""
    return get_plan_features(plan).get("monthly_tryon_limit")

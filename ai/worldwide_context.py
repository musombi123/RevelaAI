"""Country and language metadata for the existing RevelaAI services."""
from __future__ import annotations

_COUNTRIES = {
    "KE": ("Kenya", "KES", "en", 240, "50", ["Kamukunji (verify seller and part provenance)", "authorized local distributors"]),
    "US": ("United States", "USD", "en", 120, "60", ["Mouser", "DigiKey", "Amazon US (verify seller)"]),
    "DE": ("Germany", "EUR", "de", 230, "50", ["Conrad", "Reichelt", "authorized EU distributors"]),
    "CN": ("China", "CNY", "zh", 220, "50", ["LCSC", "Alibaba (verify seller and certification)"]),
    "JP": ("Japan", "JPY", "ja", 100, "50/60", ["Akizuki", "authorized Japanese distributors"]),
    "FR": ("France", "EUR", "fr", 230, "50", ["authorized French/EU distributors"]),
    "ES": ("Spain", "EUR", "es", 230, "50", ["authorized Spanish/EU distributors"]),
    "GB": ("United Kingdom", "GBP", "en", 230, "50", ["RS", "Farnell"]),
    "IN": ("India", "INR", "en", 230, "50", ["authorized Indian distributors"]),
    "CA": ("Canada", "CAD", "en", 120, "60", ["Mouser Canada", "DigiKey Canada"]),
    "AU": ("Australia", "AUD", "en", 230, "50", ["RS Australia", "element14 Australia"]),
}
_ALIASES = {
    "USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US",
    "GERMANY": "DE", "DEUTSCHLAND": "DE", "CHINA": "CN", "JAPAN": "JP",
    "KENYA": "KE", "FRANCE": "FR", "SPAIN": "ES", "UK": "GB",
    "UNITED KINGDOM": "GB", "INDIA": "IN", "CANADA": "CA", "AUSTRALIA": "AU",
}
_LANGS = {"en": "English", "de": "German", "zh": "Chinese", "ja": "Japanese", "fr": "French", "es": "Spanish", "sw": "Swahili"}


def normalize_country(country: str | None) -> str:
    value = str(country or "").strip().upper()
    if not value:
        return "KE"
    value = _ALIASES.get(value, value)
    return value if len(value) == 2 and value.isalpha() else "KE"


def resolve_worldwide_context(country: str | None = "KE", language: str | None = "") -> dict:
    code = normalize_country(country)
    name, currency, default_language, voltage, frequency, suppliers = _COUNTRIES.get(
        code, (code, "LOCAL", "en", None, "", ["local authorized distributors; quote required"])
    )
    lang = str(language or "").strip().lower() or default_language
    if lang not in _LANGS:
        lang = "en"
    return {
        "country": code,
        "country_name": name,
        "language": lang,
        "language_name": _LANGS[lang],
        "currency": currency,
        "nominal_ac_voltage_v": voltage,
        "frequency_hz": frequency,
        "supplier_directory": list(suppliers),
        "prices_verified": False,
        "price_status": "quote_required",
        "local_adaptations": ["verify the equipment nameplate, local utility and current standards"],
        "legal_awareness": ["check applicable law in the deployment jurisdiction; metadata is not legal advice"],
    }

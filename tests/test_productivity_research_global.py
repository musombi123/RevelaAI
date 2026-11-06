from research_global.engine import (
    _country_from_query,
    country_from_locale,
    detect_language,
    list_regions,
    resolve_region,
)


def test_missing_locale_does_not_force_kenya():
    assert country_from_locale("en") == "GLOBAL"


def test_locale_country_selects_region_pack():
    assert country_from_locale("fr-CA") == "CA"
    assert resolve_region("", "fr-CA", "") == "north_america"


def test_query_country_overrides_default_locale():
    assert _country_from_query("Compare inflation in Japan") == "JP"
    assert _country_from_query("What is the GDP of South Africa?") == "ZA"
    assert resolve_region("", "en-KE", _country_from_query("GDP of South Africa")) == "africa"


def test_multilingual_language_detection():
    assert detect_language("la recherche et l'économie mondiale") == "fr"
    assert detect_language("habari za uchumi na tafiti") == "sw"
    assert detect_language("الاقتصاد والبحث العلمي") == "ar"
    assert detect_language("量子研究と経済") == "ja"
    assert detect_language("कृत्रिम बुद्धिमत्ता और शोध") == "hi"


def test_regional_packs_are_config_discoverable():
    regions = {item["id"]: item for item in list_regions()}
    assert {"global", "ke", "africa", "north_america", "europe", "south_asia", "east_asia"} <= set(regions)

def test_country_mapping_and_region_resolver_cover_global_packs():
    from research_global.engine import _country_code, _region_for_country

    assert _country_code("Brazil") == "BR"
    assert _country_code("Saudi Arabia") == "SA"
    assert _country_code("South Korea") == "KR"
    assert _region_for_country("BR") == "global"
    assert _region_for_country("SA") == "global"
    assert _region_for_country("ZA") == "africa"
    assert _region_for_country("FR") == "europe"
    assert _region_for_country("IN") == "south_asia"
    assert _region_for_country("JP") == "east_asia"

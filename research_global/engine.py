"""Config-driven worldwide research: official/open-data, scholarly, news and optional SearXNG adapters."""
from __future__ import annotations
import json, logging, os, re
from functools import lru_cache
from pathlib import Path
from typing import Any
import feedparser, requests

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("revelaai.research.global")
TIMEOUT = (4, 12)
LANG_WORDS = {
 "en":{"the","and","with","what","how","why","latest","research"},
 "sw":{"na","ya","kwa","ni","habari","tafiti","uchumi","sheria"},
 "fr":{"le","la","les","des","avec","pour","recherche","économie"},
 "es":{"el","la","los","las","con","para","investigación","economía"},
 "pt":{"o","a","os","as","com","para","pesquisa","economia"},
 "de":{"der","die","das","und","mit","für","forschung","wirtschaft"},
 "ar":{"في","من","على","ما","كيف","بحث","اقتصاد"},
 "ru":{"и","в","на","для","что","как","исследование"},
 "ja":{"の","に","は","を","研究","経済"},
 "zh":{"的","和","在","是","研究","经济"},
 "hi":{"का","की","के","और","में","शोध","अर्थव्यवस्था"},
 "ko":{"의","에","은","는","연구","경제"},
}
SUPPORTED_LANGUAGES = tuple(LANG_WORDS)

def detect_language(text: str, locale: str = "en") -> str:
    value = str(text or "")
    for lang, pattern in [("ar",r"[\u0600-\u06ff]"),("ru",r"[\u0400-\u04ff]"),("ja",r"[\u3040-\u30ff]"),("zh",r"[\u4e00-\u9fff]"),("hi",r"[\u0900-\u097f]")]:
        if re.search(pattern, value): return lang
    tokens=set(re.findall(r"[\wÀ-ÿ']+",value.casefold()))
    scores={k:len(tokens&v) for k,v in LANG_WORDS.items()}
    best=max(scores,key=scores.get)
    if scores[best]: return best
    return locale.replace("_","-").split("-")[0].lower() if locale.replace("_","-").split("-")[0].lower() in SUPPORTED_LANGUAGES else "en"

def country_from_locale(locale: str) -> str:
    for part in str(locale or "").replace("_","-").split("-")[1:]:
        if len(part)==2 and part.isalpha(): return part.upper()
    return "GLOBAL"

@lru_cache(maxsize=64)
def _pack(name: str) -> dict:
    path=ROOT/"packs"/(name+".json")
    try:
        value=json.loads(path.read_text("utf-8"))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError): return {}

def list_regions() -> list[dict]:
    out=[]
    for path in sorted((ROOT/"packs").glob("*.json")):
        p=_pack(path.stem)
        out.append({"id":path.stem,"label":p.get("label",path.stem),"countries":p.get("countries",[]),"languages":p.get("languages",[]),"currency":p.get("currency"),"currencies":p.get("currencies",{}),"source_count":len(p.get("official_sources",[]))})
    return out

def _country_code(name: str) -> str:
    value=str(name or "").strip().upper()
    aliases={
        "UNITED STATES":"US","UNITED STATES OF AMERICA":"US","USA":"US","UNITED KINGDOM":"GB","UK":"GB",
        "KENYA":"KE","GERMANY":"DE","FRANCE":"FR","SPAIN":"ES","INDIA":"IN","CHINA":"CN","JAPAN":"JP",
        "SOUTH KOREA":"KR","CANADA":"CA","AUSTRALIA":"AU","BRAZIL":"BR","MEXICO":"MX","NIGERIA":"NG",
        "SOUTH AFRICA":"ZA","GHANA":"GH","UGANDA":"UG","TANZANIA":"TZ","RWANDA":"RW","ETHIOPIA":"ET",
        "EGYPT":"EG","MOROCCO":"MA","SENEGAL":"SN","PAKISTAN":"PK","BANGLADESH":"BD","SRI LANKA":"LK",
        "NEPAL":"NP","ITALY":"IT","NETHERLANDS":"NL","SWITZERLAND":"CH","SWEDEN":"SE","NORWAY":"NO",
        "PORTUGAL":"PT","POLAND":"PL","UKRAINE":"UA","RUSSIA":"RU","TURKEY":"TR","SAUDI ARABIA":"SA",
        "UNITED ARAB EMIRATES":"AE","ISRAEL":"IL","IRAN":"IR","INDONESIA":"ID","THAILAND":"TH",
        "VIETNAM":"VN","MALAYSIA":"MY","SINGAPORE":"SG","NEW ZEALAND":"NZ","ARGENTINA":"AR",
        "CHILE":"CL","COLOMBIA":"CO","PERU":"PE"
    }
    return aliases.get(value,value if re.fullmatch(r"[A-Z]{2}",value) else "GLOBAL")


def _country_from_query(query: str) -> str:
    value=str(query or "").upper()
    names=("UNITED STATES OF AMERICA","UNITED ARAB EMIRATES","SOUTH AFRICA","SOUTH KOREA",
           "UNITED KINGDOM","SAUDI ARABIA","NEW ZEALAND","SRI LANKA","NETHERLANDS",
           "BANGLADESH","SWITZERLAND","AUSTRALIA","GERMANY","FRANCE","SPAIN","INDIA","CHINA",
           "JAPAN","CANADA","BRAZIL","MEXICO","NIGERIA","KENYA","GHANA","UGANDA","TANZANIA",
           "RWANDA","ETHIOPIA","EGYPT","MOROCCO","SENEGAL","PAKISTAN","NEPAL","ITALY","RUSSIA",
           "UKRAINE","TURKEY","ISRAEL","IRAN","INDONESIA","THAILAND","VIETNAM","MALAYSIA",
           "SINGAPORE","PORTUGAL","POLAND","ARGENTINA","CHILE","COLOMBIA","PERU")
    for name in names:
        if re.search(r"(?<![A-Z])"+re.escape(name)+r"(?![A-Z])",value):
            return _country_code(name)
    return ""


def _region_for_country(country: str) -> str:
    code=str(country or "").upper()
    if code in {"KE"}: return "ke"
    if code in {"ZA","NG","GH","UG","TZ","RW","ET","EG","MA","SN"}: return "africa"
    if code in {"US","CA","MX"}: return "north_america"
    if code in {"GB","EU","DE","FR","ES","IT","NL","CH","SE","NO","PT","PL","UA"}: return "europe"
    if code in {"IN","PK","BD","LK","NP"}: return "south_asia"
    if code in {"CN","JP","KR","TW"}: return "east_asia"
    return "global"


def resolve_region(region: str, locale: str, country: str) -> str:
    wanted=re.sub(r"[^a-z0-9_-]","",str(region or "").lower())
    if wanted and _pack(wanted): return wanted
    c=(country or country_from_locale(locale)).upper()
    return _region_for_country(c)

def _item(source,title,url,snippet,**meta):
    return {"source":str(source)[:100],"title":str(title)[:500],"url":str(url)[:2000],"snippet":re.sub(r"\s+"," ",str(snippet or "")).strip()[:1800],"country":meta.get("country","GLOBAL"),"region":meta.get("region","global"),"language":meta.get("language","en"),"published_at":meta.get("published"),"retrieved":True}

def _arxiv(q,n,lang):
    r=requests.get("https://export.arxiv.org/api/query",params={"search_query":"all:"+q,"start":0,"max_results":min(n,10),"sortBy":"relevance"},timeout=TIMEOUT,headers={"User-Agent":"RevelaAI-Research/1.0"}); r.raise_for_status()
    f=feedparser.parse(r.content)
    return [_item("arXiv",x.get("title"),x.get("link"),x.get("summary"),language=lang,published=x.get("published")) for x in f.entries[:n]]

def _crossref(q,n,lang):
    r=requests.get("https://api.crossref.org/works",params={"query.bibliographic":q,"rows":min(n,10),"select":"title,author,published,URL,container-title"},timeout=TIMEOUT,headers={"User-Agent":"RevelaAI/1.0"});r.raise_for_status()
    out=[]
    for x in r.json().get("message",{}).get("items",[]):
        parts=x.get("published",{}).get("date-parts",[[]])[0]
        authors=", ".join(" ".join(filter(None,[a.get("given"),a.get("family")])) for a in x.get("author",[])[:4])
        out.append(_item("Crossref",(x.get("title") or [""])[0],x.get("URL",""),(authors+"; " if authors else "")+(x.get("container-title") or [""])[0],language=lang,published="-".join(map(str,parts)) if parts else None))
    return out

def _openalex(q,n,lang):
    r=requests.get("https://api.openalex.org/works",params={"search":q,"per-page":min(n,10),"select":"id,doi,title,publication_year,authorships"},timeout=TIMEOUT,headers={"User-Agent":"RevelaAI/1.0"});r.raise_for_status()
    out=[]
    for x in r.json().get("results",[]):
        names=", ".join((a.get("author") or {}).get("display_name","") for a in x.get("authorships",[])[:4])
        out.append(_item("OpenAlex",x.get("title"),x.get("doi") or x.get("id"),names,language=lang,published=str(x.get("publication_year") or "") or None))
    return out

def _europe_pmc(q,n,lang):
    r=requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",params={"query":q,"format":"json","pageSize":min(n,10),"resultType":"core"},timeout=TIMEOUT);r.raise_for_status()
    return [_item("Europe PMC / PubMed",x.get("title"),"https://europepmc.org/article/MED/"+str(x.get("id","")),x.get("abstractText") or x.get("authorString"),language=lang,published=x.get("firstPublicationDate")) for x in r.json().get("resultList",{}).get("result",[])]

def _gdelt(q,n,lang):
    r=requests.get("https://api.gdeltproject.org/api/v2/doc/doc",params={"query":q,"mode":"ArtList","format":"json","maxrecords":min(n,10),"sort":"HybridRel","timespan":"90d"},timeout=TIMEOUT);r.raise_for_status()
    return [_item(x.get("domain","GDELT"),x.get("title"),x.get("url"),x.get("seendate"),country=_country_code(x.get("sourceCountry") or "GLOBAL"),region=_region_for_country(_country_code(x.get("sourceCountry") or "GLOBAL")),language=x.get("language") or lang,published=x.get("seendate")) for x in r.json().get("articles",[])]

def _world_bank(q,n,lang,country):
    indicators={"gdp":"NY.GDP.MKTP.CD","gross domestic product":"NY.GDP.MKTP.CD","inflation":"FP.CPI.TOTL.ZG","population":"SP.POP.TOTL","unemployment":"SL.UEM.TOTL.ZS","debt":"GC.DOD.TOTL.GD.ZS"}
    found=next((v for k,v in indicators.items() if k in q.lower()),None)
    if not found: return []
    c=country if re.fullmatch(r"[A-Z]{2}",country or "") else "WLD"
    r=requests.get(f"https://api.worldbank.org/v2/country/{c}/indicator/{found}",params={"format":"json","per_page":min(n,10)},timeout=TIMEOUT);r.raise_for_status()
    data=r.json()
    rows=data[1] if isinstance(data,list) and len(data)>1 else []
    return [_item("World Bank Open Data",f"{x.get('indicator',{}).get('value')} — {x.get('date')}",f"https://data.worldbank.org/indicator/{found}?locations={c}",f"Value: {x.get('value')}; unit: {x.get('unit') or 'as published'}",country=c,language=lang,published=str(x.get("date"))) for x in rows if x.get("value") is not None]

def _searxng(q,n,lang):
    base=os.getenv("SEARXNG_BASE_URL","").strip().rstrip("/")
    if not base: return []
    engines={"zh":"baidu,bing","ru":"yandex,google","ko":"naver,google","ja":"google,bing","hi":"google,bing"}
    params={"q":q,"format":"json","language":lang,"categories":"general,news,science"}
    if lang in engines: params["engines"]=engines[lang]
    r=requests.get(base+"/search",params=params,timeout=TIMEOUT);r.raise_for_status()
    return [_item(x.get("engine","SearXNG"),x.get("title"),x.get("url"),x.get("content"),language=lang) for x in r.json().get("results",[])[:n]]

def _serpapi(q,n,lang,country):
    key=(os.getenv("SERPAPI_API_KEY") or os.getenv("SERPAPI_KEY") or "").strip()
    if not key: return []
    news=any(word in q.lower() for word in ("news","latest","breaking","headline"))
    params={"engine":"google_news" if news else "google","q":q,"api_key":key,"hl":lang,"num":min(n,10)}
    if country and country.upper() not in {"GLOBAL","WLD"}: params["gl"]=country.lower()
    r=requests.get("https://serpapi.com/search",params=params,timeout=TIMEOUT);r.raise_for_status()
    payload=r.json()
    rows=payload.get("news_results",[]) if news else payload.get("organic_results",[])
    code=country.upper() if re.fullmatch(r"[A-Z]{2}",country or "") else "GLOBAL"
    return [_item("SerpAPI / Google News" if news else "SerpAPI / Google",x.get("title"),x.get("link") or x.get("url"),x.get("snippet") or x.get("date"),country=code,region=_region_for_country(code),language=lang,published=x.get("date")) for x in rows[:n]]

def _duckduckgo(q,n,lang):
    from bs4 import BeautifulSoup
    r=requests.get("https://html.duckduckgo.com/html/",params={"q":q},headers={"User-Agent":"Mozilla/5.0 RevelaAI research"},timeout=TIMEOUT);r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser"); out=[]
    for item in soup.select(".result")[:n]:
        link=item.select_one(".result__a"); snippet=item.select_one(".result__snippet")
        if not link: continue
        out.append(_item("DuckDuckGo",link.get_text(" ",strip=True),link.get("href",""),snippet.get_text(" ",strip=True) if snippet else "",language=lang))
    return out

ADAPTERS={"arxiv":_arxiv,"crossref":_crossref,"openalex":_openalex,"europe_pmc":_europe_pmc,"gdelt":_gdelt,"world_bank":_world_bank,"searxng":_searxng,"serpapi":_serpapi,"duckduckgo":_duckduckgo}

def search_global(*,query:str,locale:str="en",country:str="",region:str="",source_country:str="",language:str="",limit:int=8,conflicting_views:bool=False)->dict[str,Any]:
    q=str(query or "").strip()
    if not q or len(q)>500: raise ValueError("query must contain 1–500 characters")
    response_lang=(language or "").split("-")[0].lower()
    if response_lang not in SUPPORTED_LANGUAGES: response_lang=detect_language(q,locale)
    query_lang=detect_language(q,locale)
    target_country=str(source_country or "").upper() or str(country or "").upper() or _country_from_query(q) or country_from_locale(locale)
    selected=resolve_region(region,locale,target_country)
    pack=_pack(selected); global_pack=_pack("global")
    regional_currency=(pack.get("currencies") or {}).get(target_country) or pack.get("currency")
    regional_languages=pack.get("languages") or global_pack.get("languages") or list(SUPPORTED_LANGUAGES)
    catalogue=list(global_pack.get("official_sources",[]))+list(pack.get("official_sources",[]))
    filter_country=str(source_country or "").upper()
    if filter_country: catalogue=[x for x in catalogue if str(x.get("country","GLOBAL")).upper() in {filter_country,"GLOBAL"}]
    n=max(1,min(int(limit),20)); rows=[]; errors=[]
    adapter_order=list(dict.fromkeys(list(pack.get("adapters") or [])+["serpapi","duckduckgo"]))
    for name in adapter_order:
        fn=ADAPTERS.get(name)
        if not fn: continue
        try:
            if name=="world_bank": found=fn(q,n,query_lang,target_country)
            elif name=="serpapi": found=fn(q,n,query_lang,target_country)
            else: found=fn(q,n,query_lang)
            rows.extend(found)
        except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
            errors.append({"provider":name,"reason":type(exc).__name__})
    rss_catalogue=list(global_pack.get("rss_sources",[]))+list(pack.get("rss_sources",[]))
    for feed in rss_catalogue[:20]:
        try:
            r=requests.get(feed["url"],timeout=TIMEOUT,headers={"User-Agent":"RevelaAI/1.0"});r.raise_for_status()
            for x in feedparser.parse(r.content).entries:
                title=str(x.get("title") or ""); summary=str(x.get("summary") or "")
                query_terms=[term for term in re.findall(r"[\\wÀ-ÿ']+",q.casefold()) if len(term)>2 and term not in {"the","and","for","with","what","when","where","how","latest","about","from","this","that","are","was","were","kwa","ya","na","habari","tafiti"}]
                searchable=(title+" "+summary).casefold()
                if query_terms and not any(term in searchable for term in query_terms): continue
                rows.append(_item(feed.get("name","RSS"),title,x.get("link",feed["url"]),summary,country=feed.get("country","GLOBAL"),region=feed.get("region",selected),language=feed.get("language",query_lang),published=x.get("published")))
                if len(rows)>=n*3: break
        except (requests.RequestException,ValueError,KeyError): errors.append({"provider":"rss","reason":"unavailable"})
    unique={}
    for x in rows:
        url=str(x.get("url") or "")
        if url.startswith("http") and url not in unique: unique[url]=x
    results=list(unique.values())
    if filter_country:
        results=[x for x in results if str(x.get("country","GLOBAL")).upper() in {filter_country,"GLOBAL"}]
    results=results[:n*3]
    grouped={}
    if conflicting_views:
        for x in results: grouped.setdefault(x.get("region","global"),[]).append(x)
    return {"query":q,"query_language":query_lang,"response_language":response_lang,"region":selected,"country":target_country,"currency":regional_currency,"regional_languages":regional_languages,"source_country_filter":filter_country or None,"official_source_catalogue":catalogue[:80],"sources":results,"source_count":len(results),"conflicting_views_requested":bool(conflicting_views),"conflicting_views":grouped,"conflict_note":"Regional grouping helps compare claims; it does not prove contradiction. Check definitions, dates and primary evidence." if conflicting_views else None,"partial":bool(errors),"provider_errors":errors,"translation_note":"The search adapters use the detected query language and regional search settings. Retrieved evidence keeps its original language; the existing chat model can translate and synthesize it in response_language."}

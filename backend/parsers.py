from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from playwright.sync_api import sync_playwright
from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import time
from thefuzz import fuzz

HEADLESS_MODE = True
FUZZY_THRESHOLD = 80

app = FastAPI(
    title="Game Keys Aggregator API",
    description="API для поиска и сравнения цен на игровые товары (Plati, Playerok, Ggsel)",
    version="0.0.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def parse_plati(playwright, query: str):
    browser = playwright.chromium.launch(
    headless=HEADLESS_MODE,
    args=[
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu'
    ]
    )
    context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page = context.new_page()
    search_url = f"https://plati.market/search/{query.replace(' ', '+')}"
    
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        try: page.wait_for_selector('.item-list', timeout=10000)
        except: pass
        time.sleep(3)
        
        soup = BeautifulSoup(page.content(), 'html.parser')
        results = []
        for item in soup.find_all('a', href=lambda href: href and '/itm/' in href):
            link = item.get('href', '')
            if link in getattr(parse_plati, 'seen', set()): continue
            getattr(parse_plati, 'seen', set()).add(link)
            
            parent = item.find_parent(class_='item-list__item') or item
            raw_text = parent.get_text(separator=' ', strip=True)
            
            price_match = re.search(r'(\d[\d\s]*[₽$])', raw_text)
            price = price_match.group(1).strip() if price_match else "0 ₽"
            
            clean_text = re.sub(r'\d[\d\s]*[₽$]', '', raw_text)
            clean_text = re.sub(r'продано[:\s]*\d[\d\s]*', '', clean_text, flags=re.IGNORECASE)
            title = re.sub(r'\b(Купить|Ключ|Аккаунт|Steam|GOG|Авто|Region|DLC|Выбор)\b', '', clean_text, flags=re.IGNORECASE)
            title = re.sub(r'^[A-Z0-9]+\s+', '', title).strip()
            
            if not any(word in title.lower() for word in query.lower().split()): continue
            if not link.startswith('http'): link = "https://plati.market" + link
            
            results.append({"source": "Plati.market", "title": title, "price": price, 
                            "price_num": int(re.sub(r'[^\d]', '', price) or 0), "url": link})
            if len(results) >= 5: break
        return results
    finally:
        browser.close()

def parse_playerok(playwright, query: str):
    browser = playwright.chromium.launch(
    headless=HEADLESS_MODE,
    args=[
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu'
    ]
    )
    context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page = context.new_page()
    
    try:
        slug = query.replace(' ', '-').lower()
        urls_to_try = [f"https://playerok.com/{slug}/keys", f"https://playerok.com/search?q={query.replace(' ', '+')}"]
        results = []
        seen_links = set()
        query_words = [word for word in query.lower().split() if len(word) > 2]
        
        for search_url in urls_to_try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            try:
                page.wait_for_selector('div[tabindex="0"]', timeout=5000)
                time.sleep(2)
                soup = BeautifulSoup(page.content(), 'html.parser')
                
                for card in soup.find_all('div', attrs={'tabindex': '0'}):
                    link_tag = card.find('a', href=lambda href: href and '/products/' in href)
                    if not link_tag: continue
                    
                    href = link_tag.get('href', '')
                    if href in seen_links: continue
                    seen_links.add(href)
                    
                    raw_text = card.get_text(separator=' ', strip=True)
                    price_match = re.search(r'(\d[\d\s]*[₽$])', raw_text)
                    price = price_match.group(1).strip() if price_match else "0 ₽"
                    
                    clean_title = re.sub(r'\d[\d\s]*[₽$]', '', raw_text)
                    clean_title = re.sub(r'\b(Автовыдача|Гарантия|Моментально|Без входа|Подарок|Ключи)\b', '', clean_title, flags=re.IGNORECASE).strip()
                    
                    if not any(word in clean_title.lower() for word in query_words): continue
                    
                    full_url = f"https://playerok.com{href}" if not href.startswith('http') else href
                    results.append({"source": "Playerok", "title": clean_title, "price": price, 
                                    "price_num": int(re.sub(r'[^\d]', '', price) or 0), "url": full_url})
                    if len(results) >= 5: break
                
                if len(results) > 0: break
            except: continue
        return results
    finally:
        browser.close()

def parse_ggsel(query: str):
    search_url = f"https://ggsel.net/search/{query.replace(' ', '-')}"
    
    session = requests.Session(impersonate="chrome124")
    
    session.headers.update({
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Referer": "https://ggsel.net/",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    })
    
    try:
        response = session.get(search_url, timeout=15)
        
        if response.status_code == 403 or "cloudflare" in response.text.lower():
            return []
            
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        
        time.sleep(2)
        cards = soup.find_all('div', attrs={'data-testid': 'card'})
        
        seen_links = set()
        for card in cards:
            link_tag = card.find('a', href=lambda href: href and '/catalog/product/' in href)
            if not link_tag:
                continue
            
            href = link_tag.get('href', '')
            if href in seen_links: 
                continue
            seen_links.add(href)
            
            img_tag = card.find('img')
            title = img_tag.get('alt', '').strip() if img_tag else ""
            if not title:
                seo_tag = card.find('div', attrs={'data-testid': 'seo-text'})
                title = seo_tag.get_text(separator=' ', strip=True) if seo_tag else ""
            
            price_tag = card.find('div', attrs={'data-test': 'price'})
            price = price_tag.get_text(separator=' ', strip=True) if price_tag else "0 ₽"
            
            clean_title = re.sub(r'\b(Купить|Ключ|Аккаунт|Steam|GOG|Авто|Region|DLC|Выбор|Гифт)\b', '', title, flags=re.IGNORECASE)
            clean_title = re.sub(r'\s+', ' ', clean_title).strip()
            
            query_words = [word for word in query.lower().split() if len(word) > 2]
            if not any(word in clean_title.lower() for word in query_words):
                continue
            
            full_url = f"https://ggsel.net{href}" if not href.startswith('http') else href
            price_num = int(re.sub(r'[^\d]', '', price) or 0)
            
            results.append({
                "source": "Ggsel.net",
                "title": clean_title,
                "price": price,
                "price_num": price_num,
                "url": full_url
            })
            
            if len(results) >= 5: 
                break
                
        print(f"   ✅ Успешно найдено {len(results)} товаров на Ggsel.net")
        return results
        
    except Exception as e:
        print(f"❌ Ошибка при запросе к Ggsel.net: {e}")
        return []

def group_all_items(all_items, threshold=FUZZY_THRESHOLD):
    sorted_items = sorted(all_items, key=lambda x: len(x["title"]), reverse=True)
    
    groups = []
    used_indices = set()
    
    for i, base_item in enumerate(sorted_items):
        if i in used_indices:
            continue
            
        current_group = [base_item]
        used_indices.add(i)
        base_norm = normalize_for_match(base_item["title"])
        
        for j, compare_item in enumerate(sorted_items):
            if j in used_indices:
                continue
            
            compare_norm = normalize_for_match(compare_item["title"])
            score = fuzz.token_sort_ratio(base_norm, compare_norm)
            
            if score >= threshold:
                current_group.append(compare_item)
                used_indices.add(j)
        
        groups.append(current_group)
        
    matched_groups = [g for g in groups if len(g) > 1]
    unique_items = [g[0] for g in groups if len(g) == 1]
    
    matched_groups.sort(key=lambda g: min(item["price_num"] for item in g))
    unique_items.sort(key=lambda x: x["price_num"])
    
    return matched_groups, unique_items

def normalize_for_match(text):
    text = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)
    return ' '.join(text.lower().split())

# --- API ENDPOINTS ---

@app.get("/")
def read_root():
    return {"message": "Aggregator API is running. Use /api/search?query=...", "status": "ok"}

@app.get("/api/search")
def search_items(query: str = Query(..., min_length=2, description="Название игры или товара")):
    try:
        with sync_playwright() as p:
            plati_raw = parse_plati(p, query)
            playerok_raw = parse_playerok(p, query)
        
        ggsel_raw = parse_ggsel(query)
        
        all_items = plati_raw + playerok_raw + ggsel_raw
        
        if not all_items:
            return {"query": query, "matched_groups": [], "unique_items": [], "message": "Товары не найдены"}
            
        matched_groups, unique_items = group_all_items(all_items)
        
        response_data = {
            "query": query,
            "total_found": len(all_items),
            "matched_groups": [
                {
                    "base_title": group[0]["title"],
                    "best_price": min(item["price_num"] for item in group),
                    "offers": [
                        {
                            "source": item["source"],
                            "price": item["price"],
                            "price_num": item["price_num"],
                            "url": item["url"],
                            "is_cheapest": (item["price_num"] == min(i["price_num"] for i in group))
                        }
                        for item in sorted(group, key=lambda x: x["price_num"])
                    ]
                }
                for group in matched_groups
            ],
            "unique_items": [
                {
                    "source": item["source"],
                    "title": item["title"],
                    "price": item["price"],
                    "url": item["url"]
                }
                for item in unique_items
            ]
        }
        
        return response_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при сборе данных: {str(e)}")
import asyncio
from typing import List, Dict, Any
from playwright.async_api import async_playwright
import urllib.parse

class FacebookScraper:
    def __init__(self, city: str = "lima", min_price: int = 2000, max_price: int = 15000, query: str = ""):
        self.city = city
        self.min_price = min_price
        self.max_price = max_price
        self.query = query

    async def scrape_cars(self, max_items: int = 5) -> List[Dict[str, Any]]:
        results = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.set_viewport_size({"width": 1280, "height": 800})
                
                if self.query:
                    encoded_query = urllib.parse.quote(self.query)
                    base_url = f"https://www.facebook.com/marketplace/{urllib.parse.quote(self.city)}/search/"
                    query_params = f"?query={encoded_query}&minPrice={self.min_price}&maxPrice={self.max_price}&exact=false"
                else:
                    base_url = f"https://www.facebook.com/marketplace/{urllib.parse.quote(self.city)}/vehicles"
                    query_params = f"?minPrice={self.min_price}&maxPrice={self.max_price}&exact=false"
                url = base_url + query_params
                
                print(f"Scraping URL: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                await page.wait_for_timeout(3000)
                await page.evaluate("window.scrollBy(0, 1000)")
                await page.wait_for_timeout(2000)
                
                elements = await page.locator('a[href*="/marketplace/item/"]').all()
                
                seen_urls = set()
                for el in elements:
                    if len(results) >= max_items:
                        break
                        
                    href = await el.get_attribute("href")
                    if not href or href in seen_urls:
                        continue
                    seen_urls.add(href)
                    
                    full_url = "https://www.facebook.com" + href.split("?")[0]
                    
                    text_content = await el.inner_text()
                    lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                    
                    price = ""
                    title = ""
                    image_url = ""
                    
                    img_el = el.locator('img')
                    if await img_el.count() > 0:
                        image_url = await img_el.first.get_attribute("src")
                        
                    for line in lines:
                        if ('$' in line or 'S/' in line or line.replace(',','').replace('.','').isdigit()):
                            price = line
                        elif len(line) > 5 and not price:
                            title = line
                        elif price and not title and len(line) > 5:
                            title = line
                            
                    if title and price:
                        results.append({
                            "title": title,
                            "price": price,
                            "url": full_url,
                            "image_url": image_url or "",
                            "raw_data": " | ".join(lines)
                        })
                
                await browser.close()
        except Exception as e:
            print(f"Error en scraping: {e}")
            
        return results

if __name__ == "__main__":
    scraper = FacebookScraper("lima", 3000, 15000)
    autos = asyncio.run(scraper.scrape_cars(3))
    print(autos)

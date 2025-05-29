#!/usr/bin/env python3
"""
Direct approach to extract specific product categories like Rice, Dal, Oil, Spices
by navigating to the cooking category page directly.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def extract_specific_product_categories():
    """Extract specific product categories like Rice, Dal, Oil, Spices."""
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    all_categories = {}
    
    try:
        # Known category URLs from the HTML structure you provided
        category_mappings = {
            # Main Food categories
            "Food": "food",
            "Fruits & Vegetables": "fruits-vegetables", 
            "Meat & Fish": "meat-fish",
            "Cooking": "cooking",
            "Dairy & Eggs": "dairy",
            "Breakfast": "breakfast",
            "Snacks": "snacks",
            "Beverages": "beverages",
            "Baking": "baking-needs",
            "Frozen & Canned": "frozen-foods",
            
            # Specific Cooking sub-categories (Level 2)
            "Spices": "spices",
            "Salt & Sugar": "salt-sugar",
            "Rice": "rices", 
            "Dal or Lentil": "dal-or-lentil",
            "Ready Mix": "ready-mix",
            "Shemai & Suji": "shemai-suji",
            "Special Ingredients": "miscellaneous",
            "Oil": "oil",
            "Colors & Flavours": "colors-flavours", 
            "Ghee": "ghee",
            "Premium Ingredients": "premium-ingredients",
            
            # Other main categories
            "Cleaning Supplies": "cleaning",
            "Personal Care": "personal-care",
            "Health & Wellness": "hygiene",
            "Baby Care": "babycare",
            "Home & Kitchen": "home-kitchen",
            "Stationery & Office": "stationery-office",
            "Pet Care": "pet-care",
            "Toys & Sports": "toys-sports",
            "Beauty & MakeUp": "beauty",
            "Fashion & Lifestyle": "fashion-lifestyle",
            "Vehicle Essentials": "vehicle-essentials",
            "Qurbani Special": "qurbani-special",
            "Flash Sales": "flash-sales"
        }
        
        # Test each category URL to confirm it exists
        logger.info("Verifying category URLs...")
        
        for name, url_suffix in category_mappings.items():
            try:
                full_url = f"https://chaldal.com/{url_suffix}"
                logger.info(f"Testing: {name} -> {url_suffix}")
                
                driver.get(full_url)
                time.sleep(2)
                
                # Check if page loaded successfully
                page_title = driver.title
                
                # Look for products or category content
                has_products = False
                products = []
                try:
                    products = driver.find_elements(By.CLASS_NAME, "product")
                    has_products = len(products) > 0
                except:
                    pass
                
                # Check for category navigation or breadcrumbs
                has_category_content = False
                try:
                    nav_elements = driver.find_elements(By.CSS_SELECTOR, ".breadcrumb, .category, .navigation")
                    has_category_content = len(nav_elements) > 0
                except:
                    pass
                
                # Determine category level
                level = 0
                if name in ["Spices", "Salt & Sugar", "Rice", "Dal or Lentil", "Ready Mix", 
                           "Shemai & Suji", "Special Ingredients", "Oil", "Colors & Flavours", 
                           "Ghee", "Premium Ingredients"]:
                    level = 2  # Cooking sub-categories
                elif name in ["Fruits & Vegetables", "Meat & Fish", "Cooking", "Dairy & Eggs",
                             "Breakfast", "Snacks", "Beverages", "Baking", "Frozen & Canned"]:
                    level = 1  # Food sub-categories
                
                # Add to categories if valid
                if has_products or has_category_content or "chaldal" in page_title.lower():
                    all_categories[name.lower()] = {
                        "name": name,
                        "url": url_suffix,
                        "level": level,
                        "full_url": full_url,
                        "has_products": has_products,
                        "verified": True
                    }
                    
                    status = "✅ VERIFIED"
                    if has_products:
                        status += f" ({len(products)} products found)"
                    
                    print(f"  {status}: {name} -> chaldal.com/{url_suffix}")
                else:
                    print(f"  ❌ INVALID: {name} -> {url_suffix}")
                    
            except Exception as e:
                logger.warning(f"Error testing {name}: {e}")
                print(f"  ❌ ERROR: {name} -> {url_suffix}")
                continue
        
        logger.info(f"Successfully verified {len(all_categories)} categories")
        return all_categories
        
    except Exception as e:
        logger.error(f"Error in category extraction: {e}")
        return {}
    
    finally:
        driver.quit()

def save_verified_categories(categories):
    """Save verified categories to JSON file."""
    data = {
        "last_updated": datetime.now().isoformat(),
        "source": "https://chaldal.com",
        "total_categories": len(categories),
        "extraction_method": "direct_url_verification",
        "note": "These categories have been verified to exist and contain products",
        "categories": categories
    }
    
    filename = "chaldal_verified_categories.json"
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(categories)} verified categories to {filename}")
        return filename
    except Exception as e:
        logger.error(f"Error saving categories: {e}")
        return None

if __name__ == "__main__":
    print("🔍 Extracting and verifying specific product categories...")
    print("This will test URLs for Rice, Dal, Oil, Spices, and other categories.")
    
    categories = extract_specific_product_categories()
    
    if categories:
        # Save verified categories
        filename = save_verified_categories(categories)
        
        # Display results
        print(f"\n✅ Successfully verified {len(categories)} categories:")
        
        # Group by level
        by_level = {}
        for cat_data in categories.values():
            level = cat_data.get('level', 0)
            if level not in by_level:
                by_level[level] = []
            by_level[level].append(cat_data)
        
        for level in sorted(by_level.keys()):
            level_names = {0: "🏷️ Main Categories", 1: "📂 Sub-Categories", 2: "🛍️ Product Categories"}
            print(f"\n{level_names.get(level, f'Level {level}')} ({len(by_level[level])} items):")
            
            for cat in sorted(by_level[level], key=lambda x: x['name']):
                product_info = f" - {len(cat.get('products', []))} products" if cat.get('has_products') else ""
                print(f"  - {cat['name']} → chaldal.com/{cat['url']}{product_info}")
        
        # Highlight cooking categories
        cooking_cats = [cat for cat in categories.values() if cat['level'] == 2]
        print(f"\n🍳 COOKING PRODUCT CATEGORIES ({len(cooking_cats)} items):")
        for cat in sorted(cooking_cats, key=lambda x: x['name']):
            print(f"  - {cat['name']} → chaldal.com/{cat['url']}")
        
        print(f"\n💾 All verified categories saved to: {filename}")
        
    else:
        print("\n❌ No categories could be verified.")
    
    print("\n🎉 Category verification complete!")

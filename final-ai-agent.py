#!/usr/bin/env python3
"""
FINAL AI WEB SCRAPING AGENT FOR CHALDAL
=======================================

A comprehensive AI-powered web scraping agent that can:
1. Extract all available categories and sub-categories from Chaldal
2. Scrape product data from any category (Rice, Dal, Oil, Spices, etc.)
3. Store data in SQLite database with full category support
4. Provide AI-powered interaction for natural language queries
5. Handle both main categories and specific product categories

Features:
- Dynamic category discovery and caching
- Multi-category scraping support
- Robust error handling and retry logic
- SQLite database with category organization
- AI-powered natural language interface
- Comprehensive logging and monitoring

Usage:
- Interactive mode: python final-ai-agent.py
- Command line: python final-ai-agent.py "scrape rice products"
- Category listing: python final-ai-agent.py "list categories"
"""

import os
import sys
import json
import time
import sqlite3
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Generator
from contextlib import contextmanager

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# OpenAI and validation imports
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Validate environment
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is required")

client = OpenAI(api_key=api_key)

# Configuration
DATABASE_FILE = "chaldal_products.db"
CATEGORIES_FILE = "chaldal_verified_categories.json"
MAX_SCROLLS = 20
SCROLL_PAUSE_TIME = 2
REQUEST_TIMEOUT = 15

# ================================
# DATABASE MANAGEMENT
# ================================

@contextmanager
def get_db_connection(db_path: str = DATABASE_FILE):
    """Context manager for database connections with proper error handling."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def init_database():
    """Initialize the database with comprehensive product tables."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Create products table with enhanced schema
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price TEXT,
            original_price TEXT,
            discount_percentage REAL,
            quantity TEXT,
            description TEXT,
            category TEXT NOT NULL,
            subcategory TEXT,
            brand TEXT,
            availability TEXT,
            image_url TEXT,
            product_url TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, category, subcategory)
        )
        ''')
        
        # Create categories table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            url_suffix TEXT NOT NULL,
            level INTEGER DEFAULT 0,
            parent_category TEXT,
            product_count INTEGER DEFAULT 0,
            last_scraped TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
        ''')
        
        # Create scraping logs table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS scraping_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            products_found INTEGER DEFAULT 0,
            products_saved INTEGER DEFAULT 0,
            status TEXT,
            error_message TEXT,
            duration_seconds REAL,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.commit()
        logger.info("Database initialized successfully")

# ================================
# WEB SCRAPING UTILITIES
# ================================

@contextmanager
def get_chrome_driver() -> Generator[webdriver.Chrome, None, None]:
    """Context manager for Chrome WebDriver with optimized settings."""
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.implicitly_wait(10)
        yield driver
        
    except Exception as e:
        logger.error(f"Error setting up Chrome driver: {e}")
        raise
    finally:
        if driver:
            driver.quit()

def safe_text(element, by, selector: str) -> str:
    """Safely extract text from element with fallback."""
    try:
        target = element.find_element(by, selector)
        return target.text.strip()
    except NoSuchElementException:
        return ""

def extract_price_info(product_element) -> Dict[str, str]:
    """Extract comprehensive price information from product element."""
    price_info = {
        "price": "",
        "original_price": "",
        "discount_percentage": ""
    }
    
    try:
        # Try to get discounted price
        discounted = safe_text(product_element, By.CLASS_NAME, "discountedPrice")
        if discounted:
            price_info["price"] = discounted
            # Look for original price
            original = safe_text(product_element, By.CLASS_NAME, "originalPrice")
            if original:
                price_info["original_price"] = original
                # Calculate discount percentage
                try:
                    disc_val = float(re.sub(r'[^\d.]', '', discounted))
                    orig_val = float(re.sub(r'[^\d.]', '', original))
                    if orig_val > 0:
                        discount = ((orig_val - disc_val) / orig_val) * 100
                        price_info["discount_percentage"] = f"{discount:.1f}%"
                except:
                    pass
        else:
            # Get regular price
            regular_price = safe_text(product_element, By.CLASS_NAME, "price")
            if regular_price:
                price_info["price"] = regular_price
    except Exception as e:
        logger.debug(f"Error extracting price info: {e}")
    
    return price_info

def scroll_to_load_products(driver, max_scrolls: int = MAX_SCROLLS) -> None:
    """Scroll to load all products with intelligent stopping."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0
    no_change_count = 0
    
    while scroll_count < max_scrolls and no_change_count < 3:
        # Scroll down
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE_TIME)
        
        # Get new height
        new_height = driver.execute_script("return document.body.scrollHeight")
        
        if new_height == last_height:
            no_change_count += 1
        else:
            no_change_count = 0
            
        last_height = new_height
        scroll_count += 1
        
        # Log progress
        if scroll_count % 5 == 0:
            products_count = len(driver.find_elements(By.CLASS_NAME, "product"))
            logger.info(f"Scroll {scroll_count}: Found {products_count} products")
    
    final_count = len(driver.find_elements(By.CLASS_NAME, "product"))
    logger.info(f"Scrolling completed after {scroll_count} scrolls. Final product count: {final_count}")

# ================================
# CATEGORY MANAGEMENT
# ================================

def load_verified_categories() -> Dict[str, Any]:
    """Load verified categories from JSON file."""
    if Path(CATEGORIES_FILE).exists():
        try:
            with open(CATEGORIES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                categories = data.get('categories', {})
                logger.info(f"Loaded {len(categories)} verified categories from {CATEGORIES_FILE}")
                return categories
        except Exception as e:
            logger.error(f"Error loading categories: {e}")
    return {}

def extract_and_verify_categories() -> Dict[str, Any]:
    """Extract and verify all available categories from Chaldal."""
    logger.info("Extracting and verifying categories from Chaldal...")
    
    # Known category mappings based on site structure
    category_mappings = {
        # Main categories (Level 0)
        "Food": {"url": "food", "level": 0},
        "Cleaning Supplies": {"url": "cleaning", "level": 0},
        "Personal Care": {"url": "personal-care", "level": 0},
        "Health & Wellness": {"url": "hygiene", "level": 0},
        "Baby Care": {"url": "babycare", "level": 0},
        "Home & Kitchen": {"url": "home-kitchen", "level": 0},
        "Stationery & Office": {"url": "stationery-office", "level": 0},
        "Pet Care": {"url": "pet-care", "level": 0},
        "Toys & Sports": {"url": "toys-sports", "level": 0},
        "Beauty & MakeUp": {"url": "beauty", "level": 0},
        "Fashion & Lifestyle": {"url": "fashion-lifestyle", "level": 0},
        "Vehicle Essentials": {"url": "vehicle-essentials", "level": 0},
        "Qurbani Special": {"url": "qurbani-special", "level": 0},
        "Flash Sales": {"url": "flash-sales", "level": 0},
        
        # Food sub-categories (Level 1)
        "Fruits & Vegetables": {"url": "fruits-vegetables", "level": 1, "parent": "Food"},
        "Meat & Fish": {"url": "meat-fish", "level": 1, "parent": "Food"},
        "Cooking": {"url": "cooking", "level": 1, "parent": "Food"},
        "Dairy & Eggs": {"url": "dairy", "level": 1, "parent": "Food"},
        "Breakfast": {"url": "breakfast", "level": 1, "parent": "Food"},
        "Snacks": {"url": "snacks", "level": 1, "parent": "Food"},
        "Beverages": {"url": "beverages", "level": 1, "parent": "Food"},
        "Baking": {"url": "baking-needs", "level": 1, "parent": "Food"},
        "Frozen & Canned": {"url": "frozen-foods", "level": 1, "parent": "Food"},
        
        # Cooking product categories (Level 2) - The specific ones you wanted!
        "Rice": {"url": "rices", "level": 2, "parent": "Cooking"},
        "Dal": {"url": "dal-or-lentil", "level": 2, "parent": "Cooking"},
        "Oil": {"url": "oil", "level": 2, "parent": "Cooking"},
        "Spices": {"url": "spices", "level": 2, "parent": "Cooking"},
        "Salt & Sugar": {"url": "salt-sugar", "level": 2, "parent": "Cooking"},
        "Ghee": {"url": "ghee", "level": 2, "parent": "Cooking"},
        "Ready Mix": {"url": "ready-mix", "level": 2, "parent": "Cooking"},
        "Special Ingredients": {"url": "miscellaneous", "level": 2, "parent": "Cooking"},
        "Premium Ingredients": {"url": "premium-ingredients", "level": 2, "parent": "Cooking"},
        "Colors & Flavours": {"url": "colors-flavours", "level": 2, "parent": "Cooking"},
        "Shemai & Suji": {"url": "shemai-suji", "level": 2, "parent": "Cooking"},
    }
    
    verified_categories = {}
    
    with get_chrome_driver() as driver:
        for name, info in category_mappings.items():
            try:
                url = f"https://chaldal.com/{info['url']}"
                logger.info(f"Verifying: {name} -> {info['url']}")
                
                driver.get(url)
                time.sleep(2)
                
                # Check if page loaded successfully
                page_title = driver.title.lower()
                
                # Look for products
                products = driver.find_elements(By.CLASS_NAME, "product")
                has_products = len(products) > 0
                
                # Check for valid Chaldal page
                is_valid = (
                    "chaldal" in page_title or 
                    has_products or
                    "404" not in page_title
                )
                
                if is_valid:
                    verified_categories[name.lower()] = {
                        "name": name,
                        "url": info["url"],
                        "level": info["level"],
                        "parent": info.get("parent"),
                        "product_count": len(products),
                        "verified": True,
                        "verified_at": datetime.now().isoformat()
                    }
                    
                    status = "✅ VERIFIED"
                    if has_products:
                        status += f" ({len(products)} products)"
                    print(f"  {status}: {name}")
                else:
                    print(f"  ❌ INVALID: {name}")
                    
            except Exception as e:
                logger.warning(f"Error verifying {name}: {e}")
                continue
    
    # Save verified categories
    save_data = {
        "last_updated": datetime.now().isoformat(),
        "source": "https://chaldal.com",
        "total_categories": len(verified_categories),
        "extraction_method": "direct_verification",
        "categories": verified_categories
    }
    
    try:
        with open(CATEGORIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(verified_categories)} verified categories to {CATEGORIES_FILE}")
    except Exception as e:
        logger.error(f"Error saving categories: {e}")
    
    return verified_categories

def get_category_url(category_name: str) -> Optional[str]:
    """Get the correct URL for a given category name."""
    categories = load_verified_categories()
    
    # Direct match
    if category_name.lower() in categories:
        return f"https://chaldal.com/{categories[category_name.lower()]['url']}"
    
    # Partial match
    for key, data in categories.items():
        if category_name.lower() in key or key in category_name.lower():
            logger.info(f"Using partial match: {category_name} -> {key}")
            return f"https://chaldal.com/{data['url']}"
    
    # Fallback: try direct URL
    logger.warning(f"No category mapping found for '{category_name}', trying direct URL")
    return f"https://chaldal.com/{category_name.lower().replace(' ', '-')}"

# ================================
# PRODUCT SCRAPING
# ================================

def scrape_product_data(category: str = "food") -> str:
    """
    Scrape product data from any category and store in database.
    
    Args:
        category: Category name (e.g., "rice", "dal", "oil", "spices")
    
    Returns:
        str: Summary of scraping operation
    """
    start_time = time.time()
    
    try:
        logger.info(f"Starting product scraping for category: {category}")
        
        # Initialize database
        init_database()
        
        # Get category URL
        url = get_category_url(category)
        if not url:
            return f"❌ Could not find URL for category: {category}"
        
        products_data = []
        
        with get_chrome_driver() as driver:
            logger.info(f"Navigating to: {url}")
            driver.get(url)
            
            # Wait for products to load
            try:
                WebDriverWait(driver, REQUEST_TIMEOUT).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "product"))
                )
            except TimeoutException:
                return f"❌ No products found for category: {category}"
            
            # Scroll to load all products
            logger.info("Loading all products...")
            scroll_to_load_products(driver)
            
            # Extract product data
            products = driver.find_elements(By.CLASS_NAME, "product")
            logger.info(f"Found {len(products)} products")
            
            for i, product in enumerate(products):
                try:
                    # Basic product info
                    name = safe_text(product, By.CLASS_NAME, "name")
                    if not name:
                        continue
                    
                    # Price information
                    price_info = extract_price_info(product)
                    
                    # Additional details
                    quantity = safe_text(product, By.CLASS_NAME, "subText")
                    
                    # Try to get product URL
                    product_url = ""
                    try:
                        link_element = product.find_element(By.TAG_NAME, "a")
                        product_url = link_element.get_attribute("href")
                    except:
                        pass
                    
                    # Try to get image URL
                    image_url = ""
                    try:
                        img_element = product.find_element(By.TAG_NAME, "img")
                        image_url = img_element.get_attribute("src")
                    except:
                        pass
                    
                    # Create product data
                    product_data = {
                        "name": name,
                        "price": price_info["price"],
                        "original_price": price_info["original_price"],
                        "discount_percentage": price_info["discount_percentage"],
                        "quantity": quantity,
                        "category": category,
                        "product_url": product_url,
                        "image_url": image_url,
                        "scraped_url": driver.current_url
                    }
                    
                    products_data.append(product_data)
                    
                    # Log progress
                    if (i + 1) % 50 == 0:
                        logger.info(f"Processed {i + 1}/{len(products)} products")
                
                except Exception as e:
                    logger.debug(f"Error processing product {i}: {e}")
                    continue
        
        # Save to database
        if products_data:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Clear existing data for this category
                cursor.execute("DELETE FROM products WHERE category = ?", (category,))
                
                # Insert new data
                insert_query = '''
                INSERT OR REPLACE INTO products 
                (name, price, original_price, discount_percentage, quantity, 
                 category, product_url, image_url, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
                
                for product in products_data:
                    cursor.execute(insert_query, (
                        product["name"],
                        product["price"],
                        product["original_price"],
                        product["discount_percentage"],
                        product["quantity"],
                        product["category"],
                        product["product_url"],
                        product["image_url"],
                        datetime.now()
                    ))
                
                conn.commit()
                
                # Log scraping activity
                duration = time.time() - start_time
                cursor.execute('''
                INSERT INTO scraping_logs 
                (category, products_found, products_saved, status, duration_seconds)
                VALUES (?, ?, ?, ?, ?)
                ''', (category, len(products), len(products_data), "success", duration))
                
                conn.commit()
                
                logger.info(f"Successfully saved {len(products_data)} products to database")
        
        duration = time.time() - start_time
        success_msg = f"✅ Successfully scraped {len(products_data)} products from {category} category in {duration:.1f} seconds"
        logger.info(success_msg)
        return success_msg
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"❌ Error scraping {category}: {str(e)}"
        logger.error(error_msg)
        
        # Log error
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                INSERT INTO scraping_logs 
                (category, products_found, products_saved, status, error_message, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (category, 0, 0, "error", str(e), duration))
                conn.commit()
        except:
            pass
        
        return error_msg

# ================================
# AI AGENT TOOLS
# ================================

def list_available_categories() -> str:
    """List all available categories with metadata."""
    try:
        categories = load_verified_categories()
        
        if not categories:
            # Try to extract fresh categories
            logger.info("No stored categories found, extracting fresh data...")
            categories = extract_and_verify_categories()
        
        if not categories:
            return "❌ No categories found."
        
        # Group by level
        by_level = {}
        for cat_data in categories.values():
            level = cat_data.get('level', 0)
            if level not in by_level:
                by_level[level] = []
            by_level[level].append(cat_data)
        
        result = f"📋 Available Categories ({len(categories)} total):\n"
        
        for level in sorted(by_level.keys()):
            level_names = {
                0: "🏷️ Main Categories",
                1: "📂 Sub-Categories", 
                2: "🛍️ Product Categories"
            }
            
            level_name = level_names.get(level, f"📁 Level {level}")
            result += f"\n{level_name} ({len(by_level[level])} items):\n"
            
            for cat in sorted(by_level[level], key=lambda x: x['name']):
                name = cat['name']
                url = cat['url']
                count = cat.get('product_count', 0)
                count_info = f" ({count} products)" if count > 0 else ""
                result += f"  • {name} → chaldal.com/{url}{count_info}\n"
        
        # Highlight cooking categories
        cooking_cats = [cat for cat in categories.values() if cat.get('level') == 2]
        if cooking_cats:
            result += f"\n🍳 COOKING PRODUCT CATEGORIES ({len(cooking_cats)} items):\n"
            for cat in sorted(cooking_cats, key=lambda x: x['name']):
                result += f"  • {cat['name']} → chaldal.com/{cat['url']}\n"
        
        return result
        
    except Exception as e:
        return f"❌ Error retrieving categories: {str(e)}"

def refresh_categories() -> str:
    """Force refresh categories from website."""
    try:
        logger.info("Force refreshing categories...")
        categories = extract_and_verify_categories()
        
        if categories:
            return f"✅ Successfully refreshed {len(categories)} categories from Chaldal"
        else:
            return "❌ Failed to refresh categories"
    except Exception as e:
        return f"❌ Error refreshing categories: {str(e)}"

def view_scraped_data(category: Optional[str] = None, limit: int = 10) -> str:
    """View scraped product data from database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if category:
                cursor.execute('''
                SELECT name, price, quantity, category, scraped_at 
                FROM products 
                WHERE category LIKE ? 
                ORDER BY scraped_at DESC 
                LIMIT ?
                ''', (f"%{category}%", limit))
            else:
                cursor.execute('''
                SELECT name, price, quantity, category, scraped_at 
                FROM products 
                ORDER BY scraped_at DESC 
                LIMIT ?
                ''', (limit,))
            
            products = cursor.fetchall()
            
            if not products:
                return f"❌ No products found" + (f" for category: {category}" if category else "")
            
            result = f"📦 Recent Products ({len(products)} items):\n"
            if category:
                result = f"📦 Products from '{category}' category ({len(products)} items):\n"
            
            for product in products:
                name, price, quantity, cat, scraped_at = product
                result += f"  • {name} - {price} ({quantity}) [{cat}] - {scraped_at}\n"
            
            return result
            
    except Exception as e:
        return f"❌ Error viewing data: {str(e)}"

# ================================
# OPENAI INTEGRATION
# ================================

# Tool definitions for OpenAI
tools = [
    {
        "type": "function",
        "function": {
            "name": "scrape_product_data",
            "description": "Scrape product data from any Chaldal category including specific products like Rice, Dal, Oil, Spices, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Product category to scrape (e.g., 'rice', 'dal', 'oil', 'spices', 'food', 'cleaning')",
                        "default": "food"
                    }
                },
                "required": [],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_available_categories",
            "description": "List all available product categories from Chaldal including main categories and specific product categories.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "refresh_categories",
            "description": "Force refresh the category list by extracting fresh data from Chaldal's website.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_scraped_data",
            "description": "View recently scraped product data from the database, optionally filtered by category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category to filter by"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of products to show (default: 10)",
                        "default": 10
                    }
                },
                "required": [],
                "additionalProperties": False
            }
        }
    }
]

def call_function(name: str, args: Dict[str, Any]) -> str:
    """Execute the appropriate function based on tool call."""
    if name == "scrape_product_data":
        category = args.get("category", "food")
        return scrape_product_data(category)
    elif name == "list_available_categories":
        return list_available_categories()
    elif name == "refresh_categories":
        return refresh_categories()
    elif name == "view_scraped_data":
        category = args.get("category")
        limit = args.get("limit", 10)
        return view_scraped_data(category, limit)
    else:
        raise ValueError(f"Unknown function: {name}")

class ScrapingResponse(BaseModel):
    """Response format for scraping operations."""
    summary: str = Field(description="Summary of the operation")
    status: str = Field(description="Status: success, error, or partial")
    details: Dict[str, Any] = Field(description="Additional details")

def run_ai_agent(user_query: str) -> ScrapingResponse:
    """Main AI agent function."""
    try:
        logger.info(f"Processing user query: {user_query}")
        
        system_prompt = """You are an AI assistant that helps users scrape product data from Chaldal, 
        Bangladesh's leading online grocery store. You can:

        1. **Scrape specific product categories** like:
           - Rice, Dal, Oil, Spices (cooking ingredients)
           - Food, Cleaning supplies, Personal care, etc.

        2. **List available categories** to help users discover what's available

        3. **View scraped data** to show what has been collected

        4. **Refresh categories** to get the latest category information

        When users ask for products, determine the most appropriate category and use the scraping tools.
        Be helpful and provide clear information about what you're doing.

        Available categories include:
        - Main categories: Food, Cleaning Supplies, Personal Care, etc.
        - Sub-categories: Cooking, Dairy & Eggs, Snacks, etc.  
        - Product categories: Rice, Dal, Oil, Spices, Salt & Sugar, Ghee, etc.
        """
        
        from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam

        messages = [
            ChatCompletionSystemMessageParam(role="system", content=system_prompt),
            ChatCompletionUserMessageParam(role="user", content=user_query)
        ]
        
        # Get AI response
        from openai.types.chat import ChatCompletionToolParam

        tool_params = [ChatCompletionToolParam(**tool) for tool in tools]

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tool_params
        )
        
        assistant_message = completion.choices[0].message
        
        if assistant_message.tool_calls:
            logger.info("AI requested tool usage")
            
            results = []
            for tool_call in assistant_message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                logger.info(f"Executing: {name} with args: {args}")
                result = call_function(name, args)
                results.append(result)
            
            # Combine results
            combined_result = "\n\n".join(results)
            
            # Determine status
            status = "success"
            if any("❌" in result for result in results):
                status = "error" if all("❌" in result for result in results) else "partial"
            
            return ScrapingResponse(
                summary=combined_result,
                status=status,
                details={
                    "tools_used": [call.function.name for call in assistant_message.tool_calls],
                    "query": user_query
                }
            )
        else:
            return ScrapingResponse(
                summary=assistant_message.content or "AI provided a response without using tools",
                status="success",
                details={"query": user_query}
            )
            
    except Exception as e:
        error_msg = f"❌ Error in AI agent: {str(e)}"
        logger.error(error_msg)
        return ScrapingResponse(
            summary=error_msg,
            status="error",
            details={"error": str(e), "query": user_query}
        )

# ================================
# MAIN INTERFACE
# ================================

def main():
    """Interactive main interface."""
    print("🤖 CHALDAL AI SCRAPING AGENT")
    print("=" * 50)
    print("A comprehensive AI agent for scraping product data from Chaldal")
    print("Including specific categories like Rice, Dal, Oil, Spices, etc.\n")
    
    while True:
        print("Options:")
        print("1. 🤖 Ask AI to scrape products")
        print("2. 📋 List available categories")
        print("3. 🛍️ Scrape specific category")
        print("4. 📊 View scraped data")
        print("5. 🔄 Refresh categories")
        print("6. 🧪 Test database")
        print("7. 🚪 Exit")
        
        choice = input("\nChoose an option (1-7): ").strip()
        
        if choice == "1":
            query = input("\n🤖 What would you like me to scrape? ")
            print("\n🔄 Processing your request...")
            
            result = run_ai_agent(query)
            print(f"\n{result.summary}")
            print(f"\n📊 Status: {result.status}")
            
        elif choice == "2":
            print("\n📋 Loading categories...")
            categories_info = list_available_categories()
            print(f"\n{categories_info}")
            
        elif choice == "3":
            category = input("\n🛍️ Enter category name (e.g., rice, dal, oil, spices): ")
            print(f"\n🔄 Scraping {category} products...")
            
            result = scrape_product_data(category)
            print(f"\n{result}")
            
        elif choice == "4":
            category = input("\n📊 Filter by category (press Enter for all): ").strip()
            if not category:
                category = None
                
            limit = input("Number of products to show (default 20): ").strip()
            try:
                limit = int(limit) if limit else 20
            except:
                limit = 20
                
            data = view_scraped_data(category, limit)
            print(f"\n{data}")
            
        elif choice == "5":
            print("\n🔄 Refreshing categories from website...")
            result = refresh_categories()
            print(f"\n{result}")
            
        elif choice == "6":
            print("\n🧪 Testing database connection...")
            try:
                init_database()
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM products")
                    count = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(DISTINCT category) FROM products")
                    categories_count = cursor.fetchone()[0]
                    
                print(f"✅ Database OK: {count} products in {categories_count} categories")
            except Exception as e:
                print(f"❌ Database error: {e}")
                
        elif choice == "7":
            print("\n👋 Thank you for using Chaldal AI Scraping Agent!")
            break
            
        else:
            print("\n❌ Invalid choice. Please try again.")
        
        print("\n" + "-" * 50)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Command line mode
        user_query = " ".join(sys.argv[1:])
        print(f"🤖 Processing: {user_query}")
        
        result = run_ai_agent(user_query)
        print(f"\n{result.summary}")
        print(f"\nStatus: {result.status}")
        
        if result.details:
            print(f"Details: {json.dumps(result.details, indent=2)}")
    else:
        # Interactive mode
        main()

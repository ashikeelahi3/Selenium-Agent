# Documentation: https://selenium-python.readthedocs.io/

from selenium import webdriver
from selenium.webdriver.common.by import By
import time

driver = webdriver.Chrome()
driver.get("https://chaldal.com/oil")
assert "Oil" in driver.title

def scroll_to_bottom(driver, pause_time=2):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause_time)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

# ✅ Helper: Try getting element text safely
def safe_text(product, by, name):
    try:
        return product.find_element(by, name).text
    except:
        return ""

# ✅ Helper: Try both price options
def get_price(product):
    price = safe_text(product, By.CLASS_NAME, "discountedPrice")
    return price if price else safe_text(product, By.CLASS_NAME, "price")

# Load all products
scroll_to_bottom(driver)
products = driver.find_elements(By.CLASS_NAME, "product")

# ✅ Extract data using list comprehension (no for-loop)
data = [
    {
        "id": i + 1,
        "name": safe_text(p, By.CLASS_NAME, "name"),
        "price": get_price(p),
        "quantity": safe_text(p, By.CLASS_NAME, "subText")
    }
    for i, p in enumerate(products)
]

driver.close()

print(data)

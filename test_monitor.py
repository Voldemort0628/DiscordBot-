
import sys
import time
from shopify_monitor import ShopifyMonitor

def test_monitor():
    """Test the ShopifyMonitor functionality"""
    rate_limit = 0.5  # requests per second
    
    print(f"Initializing ShopifyMonitor with rate_limit={rate_limit}")
    monitor = ShopifyMonitor(rate_limit=rate_limit)
    
    # List of stores to try (in case one fails)
    test_stores = [
        "https://www.shoepalace.com",
        "https://www.jimmyjazz.com",
        "https://www.blendsus.com"
    ]
    test_keywords = ["nike", "jordan", "dunk", "air"]
    
    # Try different stores until one works
    for test_store in test_stores:
        print(f"\nTesting store: {test_store}")
        try:
            print(f"Testing fetch_products with store={test_store}, keywords={test_keywords}")
            products = monitor.fetch_products(test_store, test_keywords)
            
            if not products:
                print(f"No matching products found on {test_store}, trying next store...")
                continue
                
            print(f"Successfully fetched {len(products)} products matching keywords")
            print("First matching product details:")
            print(f"  Title: {products[0]['title']}")
            print(f"  URL: {products[0]['url']}")
            print(f"  Price: {products[0]['price']}")
            
            print("\nTesting variant scraper:")
            product_url = products[0]['url']
            print(f"Fetching variants for {product_url}")
            variants = monitor.get_product_variants(product_url)
            variant_count = len(variants.get('variants', []))
            print(f"Found {variant_count} variants")
            
            if variant_count > 0:
                print("\nVariant details:")
                for i, variant in enumerate(variants.get('variants', [])[:3]):  # Show max 3 variants
                    print(f"  Variant {i+1}:")
                    print(f"    ID: {variant.get('id')}")
                    print(f"    Title: {variant.get('title')}")
                    print(f"    Price: {variant.get('price')}")
                    print(f"    Available: {variant.get('available')}")
                
                print("\nMonitor and variant scraper are working correctly!")
                return True
        except Exception as e:
            print(f"Error testing with {test_store}: {e}")
            print("Trying next store...")
            time.sleep(1)
    
    print("\nAll test stores failed. Please check your network connection or try again later.")
    return False

if __name__ == "__main__":
    success = test_monitor()
    sys.exit(0 if success else 1)

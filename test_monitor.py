
import sys
from shopify_monitor import ShopifyMonitor

def test_monitor():
    """Test the ShopifyMonitor functionality"""
    rate_limit = 0.5  # requests per second
    
    print(f"Initializing ShopifyMonitor with rate_limit={rate_limit}")
    monitor = ShopifyMonitor(rate_limit=rate_limit)
    
    # Test store URL - ensure it's a valid Shopify store
    test_store = "https://www.shoepalace.com"
    test_keywords = ["nike", "jordan"]
    
    print(f"Testing fetch_products with store={test_store}, keywords={test_keywords}")
    try:
        products = monitor.fetch_products(test_store, test_keywords)
        print(f"Successfully fetched {len(products)} products matching keywords")
        
        if products:
            print("First matching product details:")
            print(f"  Title: {products[0]['title']}")
            print(f"  URL: {products[0]['url']}")
            print(f"  Price: {products[0]['price']}")
        else:
            print("No matching products found")
            
        print("\nTesting variant scraper:")
        if products:
            product_url = products[0]['url']
            print(f"Fetching variants for {product_url}")
            variants = monitor.get_product_variants(product_url)
            print(f"Found {len(variants.get('variants', []))} variants")
        
        return True
    except Exception as e:
        print(f"Error testing monitor: {e}")
        return False

if __name__ == "__main__":
    success = test_monitor()
    sys.exit(0 if success else 1)

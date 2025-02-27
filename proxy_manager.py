import random
from typing import List, Optional, Dict
import logging
from logger_config import scraper_logger

logger = scraper_logger

class ProxyManager:
    def __init__(self):
        self.proxies: List[Dict[str, str]] = []
        self.failed_proxies: set = set()
        self.proxy_stats: Dict[str, Dict] = {}

    def add_proxies_from_list(self, proxy_list: str) -> int:
        """
        Add proxies from a multi-line string format
        Each line format: IP:PORT:USERNAME:PASSWORD
        Returns number of valid proxies added
        """
        added = 0
        for line in proxy_list.strip().split('\n'):
            try:
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split(':')
                if len(parts) != 4:
                    logger.warning(f"Invalid proxy format: {line}")
                    continue

                ip, port, username, password = parts
                proxy_url = f"http://{username}:{password}@{ip}:{port}"
                proxy_id = f"{ip}:{port}"

                self.proxies.append({
                    'url': proxy_url,
                    'id': proxy_id,
                    'original': line
                })
                
                if proxy_id not in self.proxy_stats:
                    self.proxy_stats[proxy_id] = {
                        'success': 0,
                        'failures': 0,
                        'last_used': 0
                    }
                added += 1

            except Exception as e:
                logger.error(f"Error parsing proxy: {line} - {str(e)}")
                continue

        logger.info(f"Added {added} proxies to the pool")
        return added

    def get_next_proxy(self) -> Optional[str]:
        """Get next working proxy URL"""
        if not self.proxies:
            return None

        # Filter out failed proxies
        working_proxies = [p for p in self.proxies if p['id'] not in self.failed_proxies]
        
        # If all proxies failed, reset and try again
        if not working_proxies:
            logger.warning("All proxies failed, resetting failed proxy list")
            self.failed_proxies.clear()
            working_proxies = self.proxies

        # Select a random working proxy
        proxy = random.choice(working_proxies)
        return proxy['url']

    def mark_proxy_failed(self, proxy_url: str):
        """Mark a proxy as failed"""
        if not proxy_url:
            return

        for proxy in self.proxies:
            if proxy['url'] == proxy_url:
                self.failed_proxies.add(proxy['id'])
                self.proxy_stats[proxy['id']]['failures'] += 1
                logger.warning(f"Marked proxy {proxy['id']} as failed")
                break

    def mark_proxy_success(self, proxy_url: str):
        """Mark a proxy request as successful"""
        if not proxy_url:
            return

        for proxy in self.proxies:
            if proxy['url'] == proxy_url:
                self.failed_proxies.discard(proxy['id'])
                self.proxy_stats[proxy['id']]['success'] += 1
                break

    def get_stats(self) -> Dict:
        """Get proxy pool statistics"""
        return {
            'total_proxies': len(self.proxies),
            'failed_proxies': len(self.failed_proxies),
            'proxy_stats': self.proxy_stats
        }

import psutil
import time
import sys
import signal
from typing import Optional

class ProcessManager:
    @staticmethod
    def find_process_by_port(port: int) -> Optional[psutil.Process]:
        """Find process using specified port"""
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    return psutil.Process(conn.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return None

    @staticmethod
    def cleanup_port(port: int = 5000, timeout: int = 5) -> bool:
        """Clean up any process using the specified port"""
        try:
            process = ProcessManager.find_process_by_port(port)
            if process:
                print(f"Found process using port {port}: PID {process.pid}")
                # Try graceful shutdown first
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except psutil.TimeoutExpired:
                    print(f"Process {process.pid} did not terminate gracefully, forcing...")
                    process.kill()
                    process.wait(timeout=1)
                print(f"Successfully terminated process {process.pid}")
                time.sleep(1)  # Give the system time to free the port
            return True
        except Exception as e:
            print(f"Error cleaning up port {port}: {e}", file=sys.stderr)
            return False

    @staticmethod
    def register_shutdown_handler():
        """Register signal handlers for graceful shutdown"""
        def shutdown_handler(signum, frame):
            print("\nReceived shutdown signal, cleaning up...")
            ProcessManager.cleanup_port()
            sys.exit(0)

        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)

    @staticmethod
    def wait_for_port_available(port: int = 5000, timeout: int = 30) -> bool:
        """Wait for port to become available"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not ProcessManager.find_process_by_port(port):
                return True
            time.sleep(1)
        return False

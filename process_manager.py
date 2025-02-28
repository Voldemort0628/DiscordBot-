import psutil
import time
import sys
import signal
from typing import Optional
import logging

class ProcessManager:
    @staticmethod
    def find_process_by_port(port: int) -> Optional[psutil.Process]:
        """Find process using specified port"""
        try:
            for conn in psutil.net_connections(kind='inet'):
                if hasattr(conn.laddr, 'port') and conn.laddr.port == port:
                    return psutil.Process(conn.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError) as e:
            print(f"Error finding process by port: {e}")
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
                    # Wait for process to terminate
                    gone, alive = psutil.wait_procs([process], timeout=timeout)
                    if alive:
                        print(f"Process {process.pid} still alive after terminate, force killing...")
                        for p in alive:
                            p.kill()
                except psutil.TimeoutExpired:
                    print(f"Process {process.pid} did not terminate gracefully, force killing...")
                    process.kill()
                except psutil.NoSuchProcess:
                    print(f"Process {process.pid} already terminated")

                # Additional verification
                time.sleep(2)  # Give OS time to fully release the port
                if ProcessManager.find_process_by_port(port):
                    print(f"Warning: Port {port} still in use after cleanup attempt")
                    return False
                print(f"Successfully terminated process on port {port}")
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
    def wait_for_port_available(port: int = 5000, timeout: int = 30, check_interval: int = 1) -> bool:
        """Wait for port to become available"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not ProcessManager.find_process_by_port(port):
                # Double check after a brief pause
                time.sleep(0.5)
                if not ProcessManager.find_process_by_port(port):
                    return True
            print(f"Port {port} still in use, waiting...")
            time.sleep(check_interval)
        return False
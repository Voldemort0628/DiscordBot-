import psutil
import time
import sys
import signal
from typing import Optional
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ProcessManager:
    @staticmethod
    def find_process_by_port(port: int) -> Optional[psutil.Process]:
        """Find process using specified port"""
        try:
            for conn in psutil.net_connections(kind='inet'):
                # Safely handle connection objects
                try:
                    if conn.laddr and len(conn.laddr) >= 2 and conn.laddr[1] == port:
                        proc = psutil.Process(conn.pid)
                        logger.info(f"Found process {proc.pid} using port {port}")
                        return proc
                except (AttributeError, IndexError) as e:
                    logger.error(f"Error processing connection: {e}")
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.error(f"Error finding process by port: {e}")
        return None

    @staticmethod
    def cleanup_port(port: int = 5000, timeout: int = 5) -> bool:
        """Clean up any process using the specified port"""
        try:
            process = ProcessManager.find_process_by_port(port)
            if process:
                logger.info(f"Found process using port {port}: PID {process.pid}")

                # Get process info before termination
                try:
                    proc_info = f"Name: {process.name()}, Command: {' '.join(process.cmdline())}"
                    logger.info(f"Process details - {proc_info}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.warning(f"Could not get process details: {e}")

                # Try graceful shutdown first
                process.terminate()
                try:
                    # Wait for process to terminate
                    gone, alive = psutil.wait_procs([process], timeout=timeout)
                    if alive:
                        logger.warning(f"Process {process.pid} still alive after terminate, force killing...")
                        for p in alive:
                            p.kill()
                except psutil.TimeoutExpired:
                    logger.warning(f"Process {process.pid} did not terminate gracefully, force killing...")
                    process.kill()
                except psutil.NoSuchProcess:
                    logger.info(f"Process {process.pid} already terminated")

                # Additional verification with increased wait time
                time.sleep(2)  # Give OS time to fully release the port
                if ProcessManager.find_process_by_port(port):
                    logger.error(f"Warning: Port {port} still in use after cleanup attempt")
                    return False
                logger.info(f"Successfully terminated process on port {port}")
            return True
        except Exception as e:
            logger.error(f"Error cleaning up port {port}: {e}", exc_info=True)
            return False

    @staticmethod
    def register_shutdown_handler():
        """Register signal handlers for graceful shutdown"""
        def shutdown_handler(signum, frame):
            logger.info("\nReceived shutdown signal, cleaning up...")
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
                    logger.info(f"Port {port} is now available")
                    return True
            logger.info(f"Port {port} still in use, waiting...")
            time.sleep(check_interval)
        logger.error(f"Timeout waiting for port {port} to become available")
        return False

    @staticmethod
    def verify_process_running(pid: int) -> bool:
        """Verify if a process is still running"""
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
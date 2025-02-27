import psutil
import time
import sys
import signal
from typing import Optional, List
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ProcessManager:
    @staticmethod
    def find_process_by_port(port: int, max_depth: int = 3) -> List[psutil.Process]:
        """Find all processes using specified port"""
        processes = []
        try:
            for conn in psutil.net_connections(kind='inet'):
                try:
                    if conn.laddr and len(conn.laddr) >= 2 and conn.laddr[1] == port:
                        proc = psutil.Process(conn.pid)
                        if proc.is_running():
                            processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    continue
        except Exception as e:
            logger.error(f"Error finding processes by port: {e}")
        return processes

    @staticmethod
    def cleanup_port(port: int = 5000, timeout: int = 5) -> bool:
        """Clean up any process using the specified port"""
        try:
            # Find all processes using the port
            processes = ProcessManager.find_process_by_port(port)
            if not processes:
                logger.info(f"No processes found using port {port}")
                return True

            success = True
            for process in processes:
                try:
                    logger.info(f"Found process using port {port}: PID {process.pid}")

                    # Get process info before termination
                    try:
                        proc_info = f"Name: {process.name()}, Command: {' '.join(process.cmdline())}"
                        logger.info(f"Process details - {proc_info}")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                    # Try graceful shutdown first
                    if process.is_running():
                        process.terminate()
                        try:
                            process.wait(timeout=timeout)
                        except psutil.TimeoutExpired:
                            logger.warning(f"Process {process.pid} did not terminate gracefully, force killing...")
                            if process.is_running():
                                process.kill()
                                process.wait(timeout=2)
                except Exception as e:
                    logger.error(f"Error terminating process {process.pid}: {e}")
                    success = False

            # Verify port is actually free
            time.sleep(1)  # Brief pause to let OS clean up
            remaining = ProcessManager.find_process_by_port(port)
            if remaining:
                pids = [p.pid for p in remaining]
                logger.error(f"Port {port} still in use by PIDs: {pids}")
                return False

            return success

        except Exception as e:
            logger.error(f"Error cleaning up port {port}: {e}")
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
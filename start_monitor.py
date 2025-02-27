
import subprocess
import sys
import time
import os
import signal
import datetime
import psutil

def kill_existing_monitors(user_id=None):
    """Kill monitor processes more reliably"""
    killed_count = 0
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if ('python' in proc.info['name'] and 
                'main.py' in cmdline and 
                "MONITOR_USER_ID=" in cmdline):
                
                # If user_id is specified, only kill that user's monitor
                if user_id and f"MONITOR_USER_ID={user_id}" not in cmdline:
                    continue
                
                pid = proc.info['pid']
                print(f"Found monitor process: PID {pid}, killing...")
                process = psutil.Process(pid)
                process.terminate()
                try:
                    process.wait(timeout=3)
                except psutil.TimeoutExpired:
                    process.kill()
                killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception) as e:
            print(f"Error handling process: {e}")
            continue
    
    print(f"Killed {killed_count} monitor processes")
    return killed_count

def start_monitor(user_id):
    # Kill any existing monitor processes for this user
    kill_existing_monitors(user_id)
    time.sleep(1)  # Give time for processes to terminate
    
    # Create a timestamp for the log file
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"monitor_log_{user_id}_{timestamp}.txt"
    
    print(f"Starting monitor for user ID: {user_id}")
    print(f"Logs will be saved to: {log_file}")
    
    # Set environment variables for better debugging
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    
    # Start the monitor process with log file
    with open(log_file, "w") as log:
        log.write(f"=== Monitor Start: {datetime.datetime.now()} ===\n")
        log.flush()
        
        try:
            # Start the monitor process
            monitor_process = subprocess.Popen(
                [sys.executable, "main.py", f"MONITOR_USER_ID={user_id}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )
            
            print(f"Monitor started with PID: {monitor_process.pid}")
            log.write(f"Monitor started with PID: {monitor_process.pid}\n")
            log.flush()
            
            # Verify process is running
            time.sleep(0.5)
            if not psutil.pid_exists(monitor_process.pid):
                print("Error: Monitor process terminated immediately")
                log.write("Error: Monitor process terminated immediately\n")
                return 1
                
        except Exception as e:
            error_msg = f"Failed to start monitor process: {e}"
            print(error_msg)
            log.write(f"{error_msg}\n")
            return 1
    
    # Stream output in real-time
    try:
        while True:
            if not psutil.pid_exists(monitor_process.pid):
                print("Monitor process has ended unexpectedly")
                break
                
            output = monitor_process.stdout.readline()
            if output:
                print(output.strip())
                with open(log_file, "a") as log:
                    log.write(output)
            elif monitor_process.poll() is not None:
                # Process has ended
                print("Monitor process ended")
                remaining_output = monitor_process.stdout.read()
                if remaining_output:
                    print(remaining_output.strip())
                    with open(log_file, "a") as log:
                        log.write(remaining_output)
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopping monitor...")
        try:
            monitor_process.terminate()
            try:
                monitor_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                monitor_process.kill()
                print("Monitor process killed")
        except Exception as e:
            print(f"Error stopping monitor: {e}")
    
    return monitor_process.returncode if monitor_process.returncode is not None else 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python start_monitor.py <user_id>")
        sys.exit(1)
    
    try:
        user_id = sys.argv[1]
        exit_code = start_monitor(user_id)
        sys.exit(exit_code)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

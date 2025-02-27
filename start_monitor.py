
import subprocess
import sys
import time
import os

def start_monitor(user_id):
    print(f"Starting monitor for user ID: {user_id}")
    
    # Set environment variable for better debugging
    os.environ["PYTHONUNBUFFERED"] = "1"
    
    # Start the monitor process
    monitor_process = subprocess.Popen(
        [sys.executable, "main.py", f"MONITOR_USER_ID={user_id}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    print(f"Monitor started with PID: {monitor_process.pid}")
    
    # Stream output in real-time
    try:
        while True:
            output = monitor_process.stdout.readline()
            if output:
                print(output.strip())
            elif monitor_process.poll() is not None:
                # Process has ended
                print("Monitor process ended")
                remaining_output = monitor_process.stdout.read()
                if remaining_output:
                    print(remaining_output.strip())
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopping monitor...")
        monitor_process.terminate()
        try:
            monitor_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            monitor_process.kill()
            print("Monitor process killed")
    
    return monitor_process.returncode

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python start_monitor.py <user_id>")
        sys.exit(1)
    
    user_id = sys.argv[1]
    exit_code = start_monitor(user_id)
    sys.exit(exit_code)

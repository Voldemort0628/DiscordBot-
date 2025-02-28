
import subprocess
import sys
import time
import os
import signal
import datetime

def start_monitor(user_id):
    # Kill any existing monitor processes
    try:
        subprocess.run(
            "pkill -f 'python main.py MONITOR_USER_ID='",
            shell=True,
            stderr=subprocess.DEVNULL
        )
        print("Killed any existing monitor processes")
        time.sleep(1)  # Give time for processes to terminate
    except Exception as e:
        print(f"Error killing existing monitors: {e}")
    
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

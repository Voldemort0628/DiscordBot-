
import os
import subprocess
import sys
import psutil
import time

def kill_existing_monitors():
    """Kill any existing monitor processes"""
    print("Looking for and killing any existing monitor processes...")
    count = 0
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if ('python' in proc.info['name'] and 
                'main.py' in cmdline and 
                "MONITOR_USER_ID=" in cmdline):
                pid = proc.info['pid']
                print(f"Found monitor process: PID {pid}, killing...")
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        process.kill()
                    count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    print(f"Error killing process {pid}: {e}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    print(f"Killed {count} monitor processes")
    time.sleep(1)  # Give processes time to fully terminate

def check_port_5000():
    """Check if anything is using port 5000"""
    processes = []
    for conn in psutil.net_connections(kind='inet'):
        try:
            if conn.laddr.port == 5000:
                proc = psutil.Process(conn.pid)
                processes.append((conn.pid, proc.name(), ' '.join(proc.cmdline())))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    if processes:
        print("Processes using port 5000:")
        for pid, name, cmdline in processes:
            print(f"PID: {pid}, Name: {name}, Command: {cmdline}")
        
        # Try to kill them
        for pid, _, _ in processes:
            try:
                process = psutil.Process(pid)
                print(f"Terminating process {pid}...")
                process.terminate()
                try:
                    process.wait(timeout=3)
                except psutil.TimeoutExpired:
                    print(f"Force killing process {pid}...")
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                print(f"Error terminating process {pid}: {e}")
    else:
        print("No processes found using port 5000")

def main():
    print("=== Monitor Fixer ===")
    
    # 1. Kill any existing monitors
    kill_existing_monitors()
    
    # 2. Check if port 5000 is in use
    check_port_5000()
    
    # 3. Test the monitor directly
    print("\nTesting monitor functionality...")
    user_id = input("Enter user ID to test (or press Enter for default ID 1): ") or "1"
    
    print(f"Starting monitor for user {user_id}...")
    try:
        subprocess.run(
            [sys.executable, "start_monitor.py", user_id],
            timeout=10,  # Only run for 10 seconds as a test
            check=True
        )
    except subprocess.TimeoutExpired:
        print("Monitor ran for 10 seconds, seems to be working")
    except subprocess.CalledProcessError as e:
        print(f"Error running monitor: {e}")
    
    print("\nFix completed. The monitor should now work properly.")
    print("To start the monitor for a specific user, run: python start_monitor.py <user_id>")

if __name__ == "__main__":
    main()

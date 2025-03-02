import psutil
import logging
import sys
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def find_discord_bot_processes():
    """Find running Discord bot processes"""
    bot_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'python' in proc.info['name'] and 'discord_bot/bot.py' in cmdline:
                bot_processes.append({
                    'pid': proc.info['pid'],
                    'cmdline': cmdline,
                    'process': psutil.Process(proc.info['pid'])
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return bot_processes

def kill_existing_bots():
    processes = find_discord_bot_processes()
    if not processes:
        print("No Discord bot processes found.")
        return True

    print(f"Found {len(processes)} Discord bot instance(s), terminating...")
    for proc_info in processes:
        try:
            process = proc_info['process']
            print(f"Terminating PID: {proc_info['pid']}")
            process.terminate()

            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                print(f"Process {proc_info['pid']} didn't terminate gracefully, forcing...")
                process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            print(f"Error terminating process {proc_info['pid']}: {e}")

    # Verify all processes are gone
    time.sleep(2)
    remaining = find_discord_bot_processes()
    if remaining:
        print(f"Warning: {len(remaining)} processes still running!")
        return False
    print("All bot processes terminated successfully.")
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--kill':
        kill_existing_bots()
    else:
        print("Checking for Discord bot instances...")
        processes = find_discord_bot_processes()
        if not processes:
            print("No Discord bot processes found.")
        else:
            print(f"Found {len(processes)} Discord bot instance(s):")
            for proc in processes:
                create_time = datetime.fromtimestamp(proc['process'].create_time())
                print(f"\nPID: {proc['pid']}")
                print(f"Command: {proc['cmdline']}")
                print(f"Running since: {create_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("\nTo terminate all instances, run: python check_bot_instances.py --kill")
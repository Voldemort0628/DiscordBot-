import subprocess
import sys
import time
import os
import signal
import datetime
import logging

def start_monitor(user_id):
    # Configure logging
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"monitor_log_{user_id}_{timestamp}.txt"

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    logging.info(f"Starting monitor for user ID: {user_id}")
    logging.info(f"Logs will be saved to: {log_file}")

    # Verify required environment variables
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        logging.error("Missing DISCORD_WEBHOOK_URL environment variable")
        return 1

    # Kill any existing monitor processes
    try:
        subprocess.run(
            "pkill -f 'python main.py MONITOR_USER_ID='",
            shell=True,
            stderr=subprocess.DEVNULL
        )
        logging.info("Killed any existing monitor processes")
        time.sleep(1)  # Give time for processes to terminate
    except Exception as e:
        logging.error(f"Error killing existing monitors: {e}")

    # Set environment variables for better debugging
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["MONITOR_USER_ID"] = str(user_id)  # Ensure user_id is set in environment

    # Start the monitor process with log file
    with open(log_file, "w") as log:
        log.write(f"=== Monitor Start: {datetime.datetime.now()} ===\n")
        log.write(f"Environment:\n")
        log.write(f"- MONITOR_USER_ID: {env.get('MONITOR_USER_ID')}\n")
        log.write(f"- DISCORD_WEBHOOK_URL: {'Set' if env.get('DISCORD_WEBHOOK_URL') else 'Not set'}\n")
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

        logging.info(f"Monitor started with PID: {monitor_process.pid}")
        log.write(f"Monitor started with PID: {monitor_process.pid}\n")
        log.flush()

    # Give the process a moment to start
    time.sleep(2)

    # Check if process is still running
    if monitor_process.poll() is not None:
        logging.error("Monitor process failed to start")
        return 1

    # Stream output in real-time
    try:
        while True:
            output = monitor_process.stdout.readline()
            if output:
                print(output.strip())
                logging.info(output.strip())
            elif monitor_process.poll() is not None:
                # Process has ended
                logging.info("Monitor process ended")
                remaining_output = monitor_process.stdout.read()
                if remaining_output:
                    print(remaining_output.strip())
                    logging.info(remaining_output.strip())
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        logging.info("Stopping monitor...")
        monitor_process.terminate()
        try:
            monitor_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            monitor_process.kill()
            logging.info("Monitor process killed")

    return monitor_process.returncode

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python start_monitor.py <user_id>")
        sys.exit(1)

    user_id = sys.argv[1]
    exit_code = start_monitor(user_id)
    sys.exit(exit_code)
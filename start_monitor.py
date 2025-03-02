import subprocess
import sys
import time
import os
import signal
import datetime
import logging
import json

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

    # Set environment variables for better debugging
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["MONITOR_USER_ID"] = str(user_id)  # Ensure user_id is set in environment

    # Create a process tracking file
    process_info = {
        "user_id": user_id,
        "start_time": datetime.datetime.now().isoformat(),
        "log_file": log_file
    }
    tracking_file = f"monitor_process_{user_id}.json"
    with open(tracking_file, "w") as f:
        json.dump(process_info, f)

    logging.info("Environment variables set:")
    logging.info(f"- MONITOR_USER_ID: {env.get('MONITOR_USER_ID')}")
    logging.info(f"- DISCORD_WEBHOOK_URL: {'Set' if env.get('DISCORD_WEBHOOK_URL') else 'Not set'}")
    logging.info(f"- Process tracking file: {tracking_file}")

    # Start the monitor process with log file
    with open(log_file, "w") as log:
        log.write(f"=== Monitor Start: {datetime.datetime.now()} ===\n")
        log.write(f"Environment:\n")
        log.write(f"- MONITOR_USER_ID: {env.get('MONITOR_USER_ID')}\n")
        log.write(f"- DISCORD_WEBHOOK_URL: {'Set' if env.get('DISCORD_WEBHOOK_URL') else 'Not set'}\n")
        log.flush()

        # Start the monitor process
        monitor_process = subprocess.Popen(
            [sys.executable, "main.py"],  # Don't pass user_id as argument, use env var
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True
        )

        logging.info(f"Monitor started with PID: {monitor_process.pid}")
        log.write(f"Monitor started with PID: {monitor_process.pid}\n")
        log.flush()

        # Update tracking file with PID
        process_info["pid"] = monitor_process.pid
        with open(tracking_file, "w") as f:
            json.dump(process_info, f)

    # Give the process a moment to start
    time.sleep(2)

    # Check if process is still running
    if monitor_process.poll() is not None:
        logging.error("Monitor process failed to start")
        # Clean up tracking file
        try:
            os.remove(tracking_file)
        except OSError:
            pass
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
    finally:
        # Clean up tracking file
        try:
            os.remove(tracking_file)
        except OSError:
            pass

    return monitor_process.returncode

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python start_monitor.py <user_id>")
        sys.exit(1)

    user_id = sys.argv[1]
    exit_code = start_monitor(user_id)
    sys.exit(exit_code)
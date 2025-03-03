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

    # Create process tracking file
    tracking_file = f"monitor_process_{user_id}.json"
    process_info = {
        "user_id": user_id,
        "start_time": datetime.datetime.now().isoformat(),
        "log_file": log_file
    }

    try:
        with open(tracking_file, "w") as f:
            json.dump(process_info, f)
        logging.info(f"Created tracking file: {tracking_file}")
    except Exception as e:
        logging.error(f"Failed to create tracking file: {e}")
        return 1

    # Verify environment
    if not os.environ.get('DISCORD_WEBHOOK_URL'):
        logging.error("Missing DISCORD_WEBHOOK_URL environment variable")
        return 1

    if str(user_id) != os.environ.get('MONITOR_USER_ID'):
        logging.error(f"User ID mismatch: argument={user_id}, environment={os.environ.get('MONITOR_USER_ID')}")
        return 1

    # Get the absolute path to main.py relative to this file
    main_script = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        'main.py'
    ))

    if not os.path.exists(main_script):
        logging.error(f"Cannot find main.py at {main_script}")
        return 1

    try:
        # Start the monitor process
        process = subprocess.Popen(
            [sys.executable, main_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ,
            start_new_session=True,
            cwd=os.path.dirname(main_script)
        )

        logging.info(f"Started process with PID {process.pid}")

        # Update tracking file with PID
        process_info["pid"] = process.pid
        with open(tracking_file, "w") as f:
            json.dump(process_info, f)
        logging.info(f"Updated tracking file with PID: {process.pid}")

        # Give the process a moment to start and check its status
        time.sleep(2)
        if process.poll() is not None:
            error_output = process.stdout.read() if process.stdout else "No error output available"
            logging.error(f"Process failed immediately. Exit code: {process.returncode}")
            logging.error(f"Process output: {error_output}")
            try:
                os.remove(tracking_file)
            except OSError:
                pass
            return 1

        # Stream output in real-time
        while True:
            output = process.stdout.readline()
            if output:
                print(output.strip())
                logging.info(output.strip())
            elif process.poll() is not None:
                remaining_output = process.stdout.read()
                if remaining_output:
                    print(remaining_output.strip())
                    logging.info(remaining_output.strip())
                break
            time.sleep(0.1)

    except Exception as e:
        logging.error(f"Error running monitor: {e}")
        return 1
    finally:
        # Clean up tracking file if process ended
        if process.poll() is not None:
            try:
                os.remove(tracking_file)
                logging.info(f"Removed tracking file: {tracking_file}")
            except OSError as e:
                logging.error(f"Error removing tracking file: {e}")

    return process.returncode

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python start_monitor.py <user_id>")
        sys.exit(1)

    user_id = sys.argv[1]
    exit_code = start_monitor(user_id)
    sys.exit(exit_code)
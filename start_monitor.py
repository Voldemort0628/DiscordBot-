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
    logging.info(f"Current working directory: {os.getcwd()}")

    # Verify required environment variables
    required_env_vars = ['DISCORD_WEBHOOK_URL', 'MONITOR_USER_ID']
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        logging.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return 1

    # Verify environment matches user_id
    env_user_id = os.environ.get('MONITOR_USER_ID')
    if str(user_id) != env_user_id:
        logging.error(f"User ID mismatch: argument={user_id}, environment={env_user_id}")
        return 1

    # Set environment variables for better debugging
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["MONITOR_USER_ID"] = str(user_id)

    # Create a process tracking file
    process_info = {
        "user_id": user_id,
        "start_time": datetime.datetime.now().isoformat(),
        "log_file": log_file
    }
    tracking_file = f"monitor_process_{user_id}.json"

    try:
        with open(tracking_file, "w") as f:
            json.dump(process_info, f)
    except Exception as e:
        logging.error(f"Failed to create tracking file: {e}")
        return 1

    logging.info("Environment variables verified:")
    logging.info(f"- MONITOR_USER_ID: {env.get('MONITOR_USER_ID')}")
    logging.info(f"- DISCORD_WEBHOOK_URL: {'Set' if env.get('DISCORD_WEBHOOK_URL') else 'Not set'}")
    logging.info(f"- Process tracking file: {tracking_file}")

    # Locate main.py
    main_script = os.path.abspath(os.path.join(os.getcwd(), "main.py"))
    if not os.path.exists(main_script):
        logging.error(f"Cannot find main.py at {main_script}")
        return 1

    logging.info(f"Found main.py at: {main_script}")

    try:
        # Start the monitor process
        monitor_process = subprocess.Popen(
            [sys.executable, main_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True
        )

        logging.info(f"Monitor started with PID: {monitor_process.pid}")

        # Update tracking file with PID
        process_info["pid"] = monitor_process.pid
        with open(tracking_file, "w") as f:
            json.dump(process_info, f)

        # Give the process a moment to start
        time.sleep(2)

        # Check if process is still running
        if monitor_process.poll() is not None:
            logging.error("Monitor process failed to start")
            logging.error(f"Process exit code: {monitor_process.returncode}")
            if monitor_process.stdout:
                error_output = monitor_process.stdout.read()
                logging.error(f"Process output: {error_output}")
            return 1

        # Stream output in real-time
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

    except Exception as e:
        logging.error(f"Error running monitor: {e}")
        return 1
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
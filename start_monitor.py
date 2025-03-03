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

    # Verify required environment variables
    required_env_vars = ['DISCORD_WEBHOOK_URL', 'MONITOR_USER_ID']
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        logging.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logging.error("Current environment:")
        logging.error(f"MONITOR_USER_ID: {os.environ.get('MONITOR_USER_ID')}")
        logging.error(f"DISCORD_WEBHOOK_URL: {'Set' if os.environ.get('DISCORD_WEBHOOK_URL') else 'Not set'}")
        return 1

    # Verify environment matches user_id
    env_user_id = os.environ.get('MONITOR_USER_ID')
    if str(user_id) != env_user_id:
        logging.error(f"User ID mismatch: argument={user_id}, environment={env_user_id}")
        return 1

    # Get the absolute path to main.py relative to this file
    main_script = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        'main.py'
    ))

    # Verify files exist
    if not os.path.exists(main_script):
        logging.error(f"Cannot find main.py at {main_script}")
        return 1

    logging.info(f"Starting monitor for user {user_id}")
    logging.info(f"main.py path: {main_script}")
    logging.info(f"Current working directory: {os.getcwd()}")

    # Setup environment
    process_env = os.environ.copy()
    process_env.update({
        'DISCORD_WEBHOOK_URL': os.environ.get('DISCORD_WEBHOOK_URL'),
        'MONITOR_USER_ID': str(user_id),
        'PYTHONUNBUFFERED': '1',
        'PYTHONPATH': os.getcwd()  # Add current directory to Python path
    })

    logging.info("Environment variables set for monitor process:")
    logging.info(f"- MONITOR_USER_ID: {process_env.get('MONITOR_USER_ID')}")
    logging.info(f"- DISCORD_WEBHOOK_URL: {'Set' if process_env.get('DISCORD_WEBHOOK_URL') else 'Not set'}")
    logging.info(f"- PYTHONPATH: {process_env.get('PYTHONPATH')}")

    try:
        # Start the monitor process
        process = subprocess.Popen(
            [sys.executable, main_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=process_env,
            start_new_session=True,
            cwd=os.path.dirname(main_script)  # Set working directory to where main.py is
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
                # Process has ended
                logging.info("Monitor process ended")
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
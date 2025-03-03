import subprocess
import sys
import time
import os
import datetime
import logging
import json
import psutil

def start_monitor(user_id):
    # Configure logging
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"monitor_log_{user_id}_{timestamp}.txt"

    # Set up logging with both file and console output
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logging.info(f"=== Starting monitor process for user ID: {user_id} ===")
    logging.info(f"Current working directory: {os.getcwd()}")
    logging.info(f"Python executable: {sys.executable}")
    logging.info(f"Python path: {os.environ.get('PYTHONPATH', 'Not set')}")

    # Verify environment variables
    required_vars = ['DISCORD_WEBHOOK_URL', 'DATABASE_URL']
    missing_vars = []
    for var in required_vars:
        value = os.environ.get(var)
        logging.info(f"Checking {var}: {'Set' if value else 'Not set'}")
        if not value:
            missing_vars.append(var)

    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logging.error(error_msg)
        return 1

    # Create process tracking file
    tracking_file = f"monitor_process_{user_id}.json"
    process_info = {
        "pid": None,
        "user_id": user_id,
        "start_time": datetime.datetime.now().isoformat(),
        "log_file": log_file
    }

    try:
        with open(tracking_file, "w") as f:
            json.dump(process_info, f)
        logging.info(f"Created tracking file: {tracking_file}")
    except Exception as e:
        logging.error(f"Failed to create tracking file: {e}", exc_info=True)
        return 1

    # Get the absolute path to main.py
    main_script = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        'main.py'
    ))

    if not os.path.exists(main_script):
        logging.error(f"Cannot find main.py at {main_script}")
        return 1

    logging.info(f"Found main script at: {main_script}")

    try:
        # Set up environment for the monitor process
        process_env = os.environ.copy()
        process_env.update({
            'MONITOR_USER_ID': str(user_id),
            'PYTHONUNBUFFERED': '1',
            'PYTHONPATH': os.getcwd()
        })

        # Start the monitor process
        process = subprocess.Popen(
            [sys.executable, main_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=process_env,
            start_new_session=True,
            cwd=os.path.dirname(main_script)
        )

        logging.info(f"Started monitor process with PID {process.pid}")

        # Update tracking file with PID
        process_info["pid"] = process.pid
        with open(tracking_file, "w") as f:
            json.dump(process_info, f)

        # Give the process a moment to start and check its status
        time.sleep(2)
        poll_result = process.poll()
        if poll_result is not None:
            error_output = process.stdout.read() if process.stdout else "No error output available"
            logging.error(f"Process failed immediately. Exit code: {poll_result}")
            logging.error(f"Process output: {error_output}")
            try:
                os.remove(tracking_file)
            except OSError:
                pass
            return 1

        # Stream output in real-time
        while True:
            line = process.stdout.readline()
            if line:
                print(line.strip())
                logging.info(f"Monitor output: {line.strip()}")
            elif process.poll() is not None:
                remaining_output = process.stdout.read()
                if remaining_output:
                    print(remaining_output.strip())
                    logging.info(f"Final output: {remaining_output.strip()}")
                break
            time.sleep(0.1)

    except Exception as e:
        logging.error(f"Error running monitor: {e}", exc_info=True)
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

    try:
        user_id = int(sys.argv[1])
        logging.info(f"Starting monitor with user_id: {user_id}")
        exit_code = start_monitor(user_id)
        logging.info(f"Monitor process exited with code: {exit_code}")
        sys.exit(exit_code)
    except ValueError:
        print(f"Invalid user_id: {sys.argv[1]}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
import subprocess
import sys
import time
import os
import datetime
import logging
import json
import psutil

def validate_environment():
    """Validate all required environment variables"""
    required_vars = {
        'DISCORD_WEBHOOK_URL': 'Discord webhook URL for notifications',
        'DATABASE_URL': 'Database connection string',
        'MONITOR_USER_ID': 'User ID for the monitor instance'
    }

    missing_vars = []
    for var, description in required_vars.items():
        value = os.environ.get(var)
        if not value:
            missing_vars.append(f"{var} ({description})")

    return missing_vars

def setup_project_paths():
    """Setup project paths and PYTHONPATH"""
    # Get the absolute path to the project root (parent directory of start_monitor.py)
    project_root = os.path.dirname(os.path.abspath(__file__))

    # Add project root to PYTHONPATH if not already there
    python_path = os.environ.get('PYTHONPATH', '')
    if project_root not in python_path.split(os.pathsep):
        new_python_path = os.pathsep.join([project_root, python_path]) if python_path else project_root
        os.environ['PYTHONPATH'] = new_python_path

    return project_root

def start_monitor(user_id):
    # Set up project paths first
    project_root = setup_project_paths()

    # Configure logging with timestamp
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f"monitor_log_{user_id}_{timestamp}.txt"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logging.info(f"=== Starting monitor process for user ID: {user_id} ===")
    logging.info(f"Project root: {project_root}")
    logging.info(f"Python executable: {sys.executable}")
    logging.info(f"Python path: {os.environ.get('PYTHONPATH')}")

    # Validate environment
    missing_vars = validate_environment()
    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logging.error(error_msg)
        return 1

    # Verify webhook URL format
    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
    if not webhook_url.startswith('https://discord.com/api/webhooks/'):
        logging.error("Invalid Discord webhook URL format")
        return 1

    # Create process tracking file
    tracking_file = f"monitor_process_{user_id}.json"
    process_info = {
        "pid": os.getpid(),
        "user_id": user_id,
        "start_time": datetime.datetime.now().isoformat(),
        "log_file": log_file,
        "python_path": os.environ.get('PYTHONPATH'),
        "working_dir": project_root
    }

    try:
        with open(tracking_file, "w") as f:
            json.dump(process_info, f)
        logging.info(f"Created tracking file: {tracking_file}")
    except Exception as e:
        logging.error(f"Failed to create tracking file: {e}", exc_info=True)
        return 1

    # Get the absolute path to main.py
    main_script = os.path.join(project_root, 'main.py')
    if not os.path.exists(main_script):
        logging.error(f"Cannot find main.py at {main_script}")
        return 1

    try:
        # Setup environment for the monitor process
        process_env = os.environ.copy()
        process_env.update({
            'MONITOR_USER_ID': str(user_id),
            'PYTHONUNBUFFERED': '1'
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
            cwd=project_root
        )

        logging.info(f"Started monitor process with PID {process.pid}")

        # Update tracking file with child process PID
        process_info["child_pid"] = process.pid
        with open(tracking_file, "w") as f:
            json.dump(process_info, f)

        # Monitor the process and log output in real-time
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
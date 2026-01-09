
import subprocess
import time
import pyautogui
import os

# Ensure the Chip2mid directory exists
os.makedirs("Chip2mid", exist_ok=True)

# Start Xvfb
xvfb_process = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x720x24"])

# Set the DISPLAY environment variable
os.environ["DISPLAY"] = ":99"

try:
    # Start the application in the background
    process = subprocess.Popen(["python", "Chip2mid/main.py"])

    # Give the application time to load
    time.sleep(5)

    # Take a screenshot
    screenshot = pyautogui.screenshot()

    # Save the screenshot
    screenshot_path = "Chip2mid/screenshot.png"
    screenshot.save(screenshot_path)

    print(f"Screenshot saved to {screenshot_path}")

finally:
    # Terminate the application process
    process.terminate()
    # Wait for the process to terminate
    process.wait()
    print("Application terminated.")
    # Stop Xvfb
    xvfb_process.terminate()

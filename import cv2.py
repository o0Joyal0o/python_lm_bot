import cv2
import numpy as np
import pyautogui
import time
import mss
import random
import threading
import pytesseract
import pytesseract; pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"  # Update path if needed
import schedule
import json
from datetime import datetime, timedelta
from queue import Queue

task_queue = Queue()
lock = threading.Lock()
DATA_FILE = "bot_data.json"

# --------------------
# Persistent Data
# --------------------
def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"resources": 0, "history": []}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

bot_data = load_data()

# --------------------
# Utility
# --------------------
def log_action(description):
    bot_data["history"].append({"time": datetime.now().isoformat(), "action": description})
    save_data(bot_data)

def human_like_move(x, y, duration=0.2):
    x += random.randint(-2, 2)
    y += random.randint(-2, 2)
    pyautogui.moveTo(x, y, duration=duration + random.uniform(-0.05, 0.05), tween=pyautogui.easeInOutQuad)

def screenshot_region(region=None):
    with mss.mss() as sct:
        if region:
            shot = np.array(sct.grab(region))
        else:
            shot = np.array(sct.grab(sct.monitors[1]))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

def find_image_on_screen(target_path, threshold=0.8):
    screenshot = screenshot_region()
    target = cv2.imread(target_path, cv2.IMREAD_COLOR)
    if target is None:
        print(f"[❌] Missing image file: {target_path}")
        return None
    result = cv2.matchTemplate(screenshot, target, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val >= threshold:
        h, w = target.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2)
    return None

def read_text_from_area(region):
    img = screenshot_region(region)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    text = pytesseract.image_to_string(gray)
    return text.strip()

def do_action(image_path, action="click", duration=1, swipe_to=None):
    pos = find_image_on_screen(image_path)
    if not pos:
        return False
    human_like_move(*pos)
    if action == "click":
        pyautogui.click()
    elif action == "hold":
        pyautogui.mouseDown()
        time.sleep(duration)
        pyautogui.mouseUp()
    elif action == "swipe" and swipe_to:
        pyautogui.mouseDown()
        human_like_move(*swipe_to, duration=duration)
        pyautogui.mouseUp()
    log_action(f"{action} on {image_path}")
    return True

# --------------------
# Task System
# --------------------
def process_task(task):
    with lock:
        task_type = task["type"]

        if task_type == "routine":
            for step in task["steps"]:
                do_action(step["image"], step.get("action", "click"), step.get("duration", 1), step.get("swipe_to"))

        elif task_type == "user_input":
            text = read_text_from_area(task["region"])
            print(f"[📖] OCR Read: {text}")
            if text == task["expected"]:
                do_action(task["on_match"]["image"], task["on_match"].get("action", "click"))
            else:
                do_action(task["on_mismatch"]["image"], task["on_mismatch"].get("action", "click"))

        elif task_type == "semi_routine":
            for step in task["steps"]:
                do_action(step["image"], step.get("action", "click"))

def task_manager():
    while True:
        task = task_queue.get()
        process_task(task)
        task_queue.task_done()

# --------------------
# Always-Running OCR Watcher
# --------------------
def ocr_watcher():
    while True:
        text = read_text_from_area({"left": 500, "top": 300, "width": 200, "height": 50})
        if text.isdigit():
            new_value = int(text)
            if new_value != bot_data["resources"]:
                # Resource change detected
                change = new_value - bot_data["resources"]
                bot_data["resources"] = new_value
                save_data(bot_data)
                print(f"[📊] Resource change: {change} (new total: {new_value})")

                # If resource reaches threshold, trigger a user input task
                if change > 0:
                    task_queue.put({
                        "type": "user_input",
                        "region": {"left": 500, "top": 300, "width": 200, "height": 50},
                        "expected": str(new_value),
                        "on_match": {"image": "thank_button.png", "action": "click"},
                        "on_mismatch": {"image": "ignore_button.png", "action": "click"}
                    })
        time.sleep(1)  # adjust speed

# --------------------
# Schedulers
# --------------------
def schedule_routines():
    schedule.every().day.at("09:00").do(lambda: task_queue.put({
        "type": "routine",
        "steps": [
            {"image": "daily_login.png", "action": "click"},
            {"image": "collect_reward.png", "action": "click"}
        ]
    }))

def schedule_semi_routines():
    last_time = datetime.now()

    def semi_routine_logic():
        nonlocal last_time
        now = datetime.now()
        if (now - last_time) >= timedelta(hours=2):
            task_queue.put({
                "type": "semi_routine",
                "steps": [
                    {"image": "check_mail.png", "action": "click"},
                    {"image": "collect_mail.png", "action": "click"}
                ]
            })
            last_time = now

    schedule.every(10).minutes.do(semi_routine_logic)

# --------------------
# Start Bot
# --------------------
if __name__ == "__main__":
    threading.Thread(target=task_manager, daemon=True).start()
    threading.Thread(target=ocr_watcher, daemon=True).start()
    schedule_routines()
    schedule_semi_routines()

    while True:
        schedule.run_pending()
        time.sleep(1)

import cv2
import numpy as np
import pyautogui
import time
import mss
import random
import threading
import pytesseract
import schedule
import json
import logging
from datetime import datetime
from queue import Queue
from typing import Dict, Any, Optional, Tuple

# =====================
# CONFIG
# =====================
TESSERACT_PATH = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
ASSETS_DIR = "assets"
DATA_FILE = "bot_data.json"
LOG_FILE = "bot.log"

PRIMARY_MONITOR_INDEX = 1
DEFAULT_OCR_PSM = 7

TEMPLATE_THRESHOLD = 0.84
MATCH_RETRIES = 3
MATCH_RETRY_SLEEP = (0.25, 0.45)

HUMAN_JITTER = 2
MOVE_DURATION = 0.2

ACTION_COOLDOWN_SECONDS = 0.8
FAILSAFE_ENABLED = True

# =====================
# GLOBALS
# =====================
pyautogui.FAILSAFE = FAILSAFE_ENABLED
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

task_queue: "Queue[Dict[str, Any]]" = Queue()
stop_event = threading.Event()

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("LM-BOT")

# =====================
# Persistent Data
# =====================
def load_data() -> Dict[str, Any]:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "resources": 0,
            "players": {},
            "history": [],
            "counters": {},
            "last_run": {},
        }

def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

bot_data = load_data()
last_action_time = 0.0

# =====================
# Utility helpers
# =====================
def cooldown_ok() -> bool:
    global last_action_time
    now = time.time()
    if now - last_action_time >= ACTION_COOLDOWN_SECONDS:
        last_action_time = now
        return True
    return False

def log_action(description: str) -> None:
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "action": description}
    bot_data.setdefault("history", []).append(entry)
    if len(bot_data["history"]) > 1000:
        bot_data["history"] = bot_data["history"][-1000:]
    save_data(bot_data)
    logger.info(description)

def human_like_move(x: int, y: int, duration: float = MOVE_DURATION) -> None:
    x += random.randint(-HUMAN_JITTER, HUMAN_JITTER)
    y += random.randint(-HUMAN_JITTER, HUMAN_JITTER)
    pyautogui.moveTo(
        x, y,
        duration=duration + random.uniform(-0.05, 0.05),
        tween=pyautogui.easeInOutQuad
    )

def screenshot_region(region: Optional[Dict[str, int]] = None) -> np.ndarray:
    with mss.mss() as sct:
        if region is None:
            shot = np.array(sct.grab(sct.monitors[PRIMARY_MONITOR_INDEX]))
        else:
            shot = np.array(sct.grab(region))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

def find_image_on_screen(target_path: str, threshold: float = TEMPLATE_THRESHOLD) -> Optional[Tuple[int, int]]:
    screenshot = screenshot_region()
    target = cv2.imread(target_path, cv2.IMREAD_COLOR)
    if target is None:
        logger.error(f"Missing image file: {target_path}")
        return None
    result = cv2.matchTemplate(screenshot, target, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val >= threshold:
        h, w = target.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2)
    return None

def read_text_from_area(region: Dict[str, int], psm: int = DEFAULT_OCR_PSM) -> str:
    img = screenshot_region(region)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 35, 35)
    custom = f"--psm {psm}"
    text = pytesseract.image_to_string(gray, config=custom)
    return text.strip()

# =====================
# Actions
# =====================
def do_action(image_path: Optional[str] = None, action: str = "click", duration: float = 1.0,
              swipe_to: Optional[Tuple[int, int]] = None, text: Optional[str] = None,
              timeout: Optional[int] = None, region: Optional[Dict[str, int]] = None) -> bool:
    if not cooldown_ok():
        time.sleep(0.1)

    pos = None
    if image_path:
        full_path = image_path if image_path.lower().endswith((".png", ".jpg")) else f"{ASSETS_DIR}/{image_path}"
        for _ in range(MATCH_RETRIES):
            pos = find_image_on_screen(full_path)
            if pos:
                break
            time.sleep(random.uniform(*MATCH_RETRY_SLEEP))
        if not pos and action not in ("wait_for", "read"):
            logger.warning(f"Failed to locate: {full_path}")
            return False

    if pos:
        human_like_move(*pos)

    # =====================
    # Actions details
    # =====================
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

    elif action == "write" and text:
        pyautogui.typewrite(text, interval=0.05)

    elif action == "wait":
        time.sleep(duration)

    elif action == "wait_for" and image_path:
        start = time.time()
        full_path = image_path if image_path.lower().endswith((".png", ".jpg")) else f"{ASSETS_DIR}/{image_path}"
        while True:
            if find_image_on_screen(full_path):
                break
            if timeout and (time.time() - start > timeout):
                logger.warning(f"Timeout waiting for {image_path}")
                return False
            time.sleep(1)

    elif action == "read" and region:
        text_val = read_text_from_area(region)
        logger.info(f"OCR Read: {text_val}")

    else:
        logger.debug(f"Unknown or no-op action: {action}")

    log_action(f"{action} on {image_path or pos}")
    return True

# =====================
# Transaction logger
# =====================
def record_transaction(player, action, resource, amount):
    if player not in bot_data["players"]:
        bot_data["players"][player] = {"sent": {}, "taken": {}}
    if resource not in bot_data["players"][player][action]:
        bot_data["players"][player][action][resource] = 0
    bot_data["players"][player][action][resource] += amount

    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "player": player,
        "action": action,
        "resource": resource,
        "amount": amount
    }
    bot_data["history"].append(entry)
    save_data(bot_data)
    logger.info(f"Transaction recorded: {player} {action} {amount} {resource}")

# =====================
# Task System
# =====================
def enqueue(task: Dict[str, Any]) -> None:
    task_queue.put(task)

def resolve_ref(task):
    if isinstance(task, dict) and "ref" in task:
        return PLAYBOOKS[task["ref"]]
    return task

# =====================
# Task Processor
# =====================
def process_task(task):
    success = True
    task_type = task["type"]

    if task_type == "routine":
        for step in task["steps"]:
            ok = do_action(
                step.get("image"),
                step.get("action", "click"),
                step.get("duration", 1),
                step.get("swipe_to"),
                step.get("text"),
                step.get("timeout"),
                step.get("region")
            )
            if not ok:
                success = False
                break

    elif task_type == "user_input":
        text = read_text_from_area(task["region"])
        logger.info(f"OCR Read: {text}")
        if text == task["expected"]:
            success = do_action(task["on_match"]["image"], task["on_match"].get("action", "click"))
        else:
            success = do_action(task["on_mismatch"]["image"], task["on_mismatch"].get("action", "click"))

    # Retry logic
    if not success and "retry" in task:
        retries = task.get("_retries", 0)
        max_attempts = task["retry"].get("max_attempts", 1)
        cooldown = task["retry"].get("cooldown", 60)
        if retries < max_attempts:
            task["_retries"] = retries + 1
            logger.warning(f"Retry {task['_retries']}/{max_attempts} after {cooldown}s")
            threading.Timer(cooldown, lambda: enqueue(task)).start()
            return
        else:
            logger.error("Task failed permanently")

    if success and "on_success" in task:
        enqueue(resolve_ref(task["on_success"]))
    elif not success and "on_fail" in task:
        enqueue(resolve_ref(task["on_fail"]))

# =====================
# Workers
# =====================
def task_manager():
    while not stop_event.is_set():
        task = task_queue.get()
        try:
            process_task(task)
        except Exception as e:
            logger.exception(f"Error: {e}")
        finally:
            task_queue.task_done()

def ocr_watcher():
    region = {"left": 500, "top": 300, "width": 200, "height": 50}
    last_val = bot_data.get("resources", 0)
    while not stop_event.is_set():
        text = read_text_from_area(region, psm=7)
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            try:
                new_val = int(digits)
            except ValueError:
                new_val = last_val
            if new_val != last_val:
                change = new_val - last_val
                last_val = new_val
                bot_data["resources"] = new_val
                save_data(bot_data)
                logger.info(f"Resource Δ {change} => {new_val}")
        time.sleep(1)

# =====================
# Playbooks
# =====================
PLAYBOOKS = {
    "daily_login": {
        "type": "routine",
        "steps": [
            {"image": "daily_login.png", "action": "click"},
            {"image": "collect_reward.png", "action": "click"},
        ]
    },
    "guild_help": {
        "type": "routine",
        "steps": [
            {"image": "guild_icon.png", "action": "click"},
            {"image": "help_all.png", "action": "click"},
            {"image": "close.png", "action": "click"},
        ]
    }
}

# =====================
# Scheduler
# =====================
def schedule_routines():
    schedule.every().day.at("08:55").do(lambda: enqueue(PLAYBOOKS["daily_login"]))
    schedule.every(30).minutes.do(lambda: enqueue(PLAYBOOKS["guild_help"]))

# =====================
# Bootstrap
# =====================
def main():
    logger.info("Starting Lords Mobile Bot")
    threading.Thread(target=task_manager, daemon=True).start()
    threading.Thread(target=ocr_watcher, daemon=True).start()
    schedule_routines()

    try:
        while not stop_event.is_set():
            schedule.run_pending()
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop_event.set()
        logger.info("Bot stopped.")

if __name__ == "__main__":
    main()

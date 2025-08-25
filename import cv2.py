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
from datetime import datetime, timedelta
from queue import Queue
from typing import Dict, Any, List, Optional, Tuple

# =====================
# CONFIG
# =====================
# --- Paths ---
TESSERACT_PATH = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"  # <- adjust if needed
ASSETS_DIR = "assets"  # folder where all UI templates live (PNG files)
DATA_FILE = "bot_data.json"
LOG_FILE = "bot.log"

# --- Screen / OCR ---
PRIMARY_MONITOR_INDEX = 1  # mss uses 1-based index for monitors
DEFAULT_OCR_PSM = 7  # Treat the image as a single text line (adjust if needed)

# --- Matching ---
TEMPLATE_THRESHOLD = 0.84
MATCH_RETRIES = 3
MATCH_RETRY_SLEEP = (0.25, 0.45)  # min, max seconds between retries

# --- Mouse movement ---
HUMAN_JITTER = 2
MOVE_DURATION = 0.2

# --- Cooldowns (to avoid spam) ---
ACTION_COOLDOWN_SECONDS = 0.8

# --- Safety ---
FAILSAFE_ENABLED = True  # pyautogui failsafe: move mouse to a corner to abort

# =====================
# GLOBALS
# =====================
pyautogui.FAILSAFE = FAILSAFE_ENABLED
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# Queues, Locks & Events
task_queue: "Queue[Dict[str, Any]]" = Queue()
lock = threading.Lock()
stop_event = threading.Event()

# Logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("LM-BOT")

# Persistent bot data

def load_data() -> Dict[str, Any]:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "resources": 0,
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
    # keep history from growing unbounded
    if len(bot_data["history"]) > 1000:
        bot_data["history"] = bot_data["history"][-1000:]
    save_data(bot_data)
    logger.info(description)


def human_like_move(x: int, y: int, duration: float = MOVE_DURATION) -> None:
    x += random.randint(-HUMAN_JITTER, HUMAN_JITTER)
    y += random.randint(-HUMAN_JITTER, HUMAN_JITTER)
    pyautogui.moveTo(x, y, duration=duration + random.uniform(-0.05, 0.05), tween=pyautogui.easeInOutQuad)


def screenshot_region(region: Optional[Dict[str, int]] = None) -> np.ndarray:
    with mss.mss() as sct:
        if region is None:
            shot = np.array(sct.grab(sct.monitors[PRIMARY_MONITOR_INDEX]))
        else:
            shot = np.array(sct.grab(region))
    # BGRA -> BGR
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
    # A little denoise & sharpen can help OCR
    gray = cv2.bilateralFilter(gray, 7, 35, 35)
    # Custom config for single-line / digits depending on use case
    custom = f"--psm {psm}"
    text = pytesseract.image_to_string(gray, config=custom)
    return text.strip()


def do_action(image_path: str, action: str = "click", duration: float = 1.0, swipe_to: Optional[Tuple[int, int]] = None) -> bool:
    global last_action_time
    if not cooldown_ok():
        time.sleep(max(0.05, ACTION_COOLDOWN_SECONDS - (time.time() - last_action_time)))
    full_path = image_path if (image_path.lower().endswith('.png') or image_path.lower().endswith('.jpg')) else f"{ASSETS_DIR}/{image_path}"

    for i in range(MATCH_RETRIES):
        pos = find_image_on_screen(full_path)
        if pos:
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
            log_action(f"{action} on {full_path}")
            return True
        time.sleep(random.uniform(*MATCH_RETRY_SLEEP))
    logger.warning(f"Failed to locate: {full_path}")
    return False

# =====================
# Task System
# =====================
# Task schema examples (dicts):
#  - routine: {"type":"routine", "steps":[{"image":"daily_login.png","action":"click"}, ...], "on_success": {...}, "on_fail": {...}}
#  - user_input: {"type":"user_input", "region":{...}, "expected":"123", "on_match": {"image":"thank.png", "action":"click", "next_task": {...}}, "on_mismatch": {...}}
#  - semi_routine: {"type":"semi_routine", "steps":[...], "followup": {...}}
#  - wait_for: {"type":"wait_for", "image":"ok.png", "timeout": 10, "then": {...}}
#  - spawn: {"type":"spawn", "tasks":[ {...}, {...} ]}

def record_transaction(player, action, resource, amount):
    """Logs a send/take transaction per player and saves to JSON."""
    if player not in bot_data["players"]:
        bot_data["players"][player] = {"sent": {}, "taken": {}}

    # Update their ledger
    if resource not in bot_data["players"][player][action]:
        bot_data["players"][player][action][resource] = 0
    bot_data["players"][player][action][resource] += amount

    # Save in history
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

def enqueue(task: Dict[str, Any]) -> None:
    task_queue.put(task)


def process_task(task):
    with lock:
        task_type = task["type"]
        success = True

        if task_type == "routine":
            for step in task["steps"]:
                ok = do_action(step["image"], step.get("action", "click"),
                               step.get("duration", 1), step.get("swipe_to"))
                if not ok:
                    success = False
                    break

        elif task_type == "user_input":
            text = read_text_from_area(task["region"])
            logging.info(f"OCR Read: {text}")
            if text == task["expected"]:
                success = do_action(task["on_match"]["image"], task["on_match"].get("action", "click"))
            else:
                success = do_action(task["on_mismatch"]["image"], task["on_mismatch"].get("action", "click"))

        elif task_type == "semi_routine":
            for step in task["steps"]:
                ok = do_action(step["image"], step.get("action", "click"))
                if not ok:
                    success = False
                    break

        # ------------------
        # Handle retry logic
        # ------------------
        if not success and "retry" in task:
            retries = task.get("_retries", 0)  # hidden field for current retries
            max_attempts = task["retry"].get("max_attempts", 1)
            cooldown = task["retry"].get("cooldown", 60)

            if retries < max_attempts:
                task["_retries"] = retries + 1
                logging.warning(f"Task failed, retry {task['_retries']}/{max_attempts} after {cooldown}s")
                threading.Timer(cooldown, lambda: task_queue.put(task)).start()
            else:
                logging.error("Task failed permanently after max retries")

        elif success and "on_success" in task:
            task_queue.put(task["on_success"])

        elif not success and "on_fail" in task:
            task_queue.put(task["on_fail"])

# =====================
# Workers
# =====================

def task_manager():
    while not stop_event.is_set():
        task = task_queue.get()
        try:
            with lock:
                process_task(task)
        except Exception as e:
            logger.exception(f"Error processing task: {e}")
        finally:
            task_queue.task_done()


def ocr_watcher():
    # Example watcher tuned for a numeric resource counter in Lords Mobile HUD region
    region = {"left": 500, "top": 300, "width": 200, "height": 50}
    last_val = bot_data.get("resources", 0)

    while not stop_event.is_set():
        text = read_text_from_area(region, psm=7)
        # Remove commas/spaces and keep digits only
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
                print(f"[RES] Δ {change} (now {new_val})")
                logger.info(f"Resource change {change} => {new_val}")

                # Example: spawn a thank-you click when resources rise
                if change > 0:
                    enqueue({
                        "type": "wait_for",
                        "image": "thank_button.png",
                        "timeout": 5,
                        "then": {"type": "routine", "steps": [{"image": "thank_button.png", "action": "click"}]}
                    })
        time.sleep(1)


# =====================
# Lords Mobile: Example Playbooks (edit image names to your assets)
# =====================

PLAYBOOKS = {
    "daily_login": {
        "type": "routine",
        "steps": [
            {"image": "daily_login.png", "action": "click"},
            {"image": "collect_reward.png", "action": "click"},
        ],
        "on_success": {"type": "spawn", "tasks": [
            {"type": "routine", "steps": [
                {"image": "vip_chest.png", "action": "click"},
                {"image": "open.png", "action": "click"},
            ]},
            {"type": "routine", "steps": [
                {"image": "mystery_box.png", "action": "click"},
                {"image": "open.png", "action": "click"},
            ]},
        ]}
    },
    "guild_help": {
        "type": "routine",
        "steps": [
            {"image": "guild_icon.png", "action": "click"},
            {"image": "help_all.png", "action": "click"},
            {"image": "close.png", "action": "click"},
        ]
    },
    "collect_mail": {
        "type": "routine",
        "steps": [
            {"image": "mail_icon.png", "action": "click"},
            {"image": "collect_mail.png", "action": "click"},
            {"image": "close.png", "action": "click"},
        ]
    },
    "cargo_ship": {
        "type": "routine",
        "steps": [
            {"image": "cargo_ship.png", "action": "click"},
            {"image": "free_trade.png", "action": "click"},
            {"image": "confirm.png", "action": "click"},
            {"image": "close.png", "action": "click"},
        ]
    }
}


# =====================
# Schedulers
# =====================

def schedule_routines():
    # Daily logins
    schedule.every().day.at("08:55").do(lambda: enqueue(PLAYBOOKS["daily_login"]))
    schedule.every().day.at("21:05").do(lambda: enqueue(PLAYBOOKS["daily_login"]))

    # Guild help every 30 minutes
    schedule.every(30).minutes.do(lambda: enqueue(PLAYBOOKS["guild_help"]))

    # Mail collection every 2 hours
    def semi_routine_logic():
        last_time_iso = bot_data.get("last_run", {}).get("collect_mail")
        now = datetime.now()
        if last_time_iso:
            try:
                last_time = datetime.fromisoformat(last_time_iso)
            except ValueError:
                last_time = now - timedelta(hours=3)
        else:
            last_time = now - timedelta(hours=3)

        if (now - last_time) >= timedelta(hours=2):
            enqueue(PLAYBOOKS["collect_mail"])
            bot_data.setdefault("last_run", {})["collect_mail"] = now.isoformat(timespec="seconds")
            save_data(bot_data)

    schedule.every(10).minutes.do(semi_routine_logic)

    # Cargo ship hourly
    schedule.every().hour.at(":10").do(lambda: enqueue(PLAYBOOKS["cargo_ship"]))


# =====================
# Bootstrap
# =====================

def main():
    logger.info("Starting Lords Mobile Bot")
    threading.Thread(target=task_manager, daemon=True, name="TaskManager").start()
    threading.Thread(target=ocr_watcher, daemon=True, name="OCRWatcher").start()

    schedule_routines()

    try:
        while not stop_event.is_set():
            schedule.run_pending()
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Stopping...")
    finally:
        stop_event.set()
        # Drain queue quickly
        while not task_queue.empty():
            try:
                task_queue.get_nowait()
                task_queue.task_done()
            except Exception:
                break
        logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
#hi
task_queue.put({
    "type": "routine",
    "steps": [
        {"image": "daily_login.png", "action": "click"},
        {"image": "collect_reward.png", "action": "click"}
    ],
    "retry": {"max_attempts": 3, "cooldown": 30},  # retry 3 times every 30s
    "on_success": {"type": "routine", "steps": [{"image": "open_mail.png"}]},
    "on_fail": {"type": "routine", "steps": [{"image": "report_issue.png"}]}
})

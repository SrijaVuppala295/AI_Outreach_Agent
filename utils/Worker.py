# utils/Worker.py
import os
import re
import time
import threading
import logging
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
import smtplib
from email.message import EmailMessage

load_dotenv()

# ---------------- CONFIG (changeable, ALL CAPS) ----------------
INTERVAL_SECONDS = 30                       # seconds to sleep between batches when tasks exist
EMPTY_LIST_INTERVAL = 10                    # seconds to sleep when task list is empty
DEBUG = True                                # enable debug prints
ADDRESS_ENV_PREFIX = "EMAIL_ADDRESS_"       # env var prefix for addresses
PASSWORD_ENV_PREFIX = "EMAIL_PASSWORD_"     # env var prefix for passwords
LOG_DIR = "logs"                            # directory to save logs
LOG_FILENAME = "worker.log"                 # filename inside LOG_DIR
# ----------------------------------------------------------------

class Worker:
    """
    Class-only background worker.
    Public API:
      Worker.start()                         # start background loop (loads accounts once)
      Worker.add_task(task: dict)            # add tasks from anywhere
      Worker.stop()                          # stop worker gracefully

    Task schema:
      For send:
        {"email": "<recipient>", "email_type": "send", "instagram": "<link>"}
      For reply (required fields):
        {"email": "<recipient>", "email_type": "reply", "instagram": "<link>",
         "original_email_id": "<message-id>", "sheet_name": "<google-sheet-name>"}
    """

    # class-level queue and locks
    _emails_to_send: List[Dict[str, Any]] = []
    _task_lock = threading.Lock()

    # control / thread handles
    _stop_event = threading.Event()
    _thread: Optional[threading.Thread] = None
    _running_lock = threading.Lock()

    # logger
    _logger: Optional[logging.Logger] = None
    _logger_initialized = False

    # loaded accounts (populated ONCE at start())
    EMAIL_ACCOUNTS: List[Dict[str, str]] = []

    # expose configs
    INTERVAL_SECONDS = INTERVAL_SECONDS
    EMPTY_LIST_INTERVAL = EMPTY_LIST_INTERVAL
    DEBUG = DEBUG
    ADDRESS_ENV_PREFIX = ADDRESS_ENV_PREFIX
    PASSWORD_ENV_PREFIX = PASSWORD_ENV_PREFIX
    LOG_DIR = LOG_DIR
    LOG_FILENAME = LOG_FILENAME

    # ---------------- logger init ----------------
    @classmethod
    def _init_logger(cls) -> None:
        if cls._logger_initialized:
            return

        try:
            os.makedirs(cls.LOG_DIR, exist_ok=True)
        except Exception:
            # continue even if mkdir fails (file handler may fail later)
            pass

        logger = logging.getLogger("Worker")
        logger.setLevel(logging.DEBUG if cls.DEBUG else logging.INFO)

        if not logger.handlers:
            # Console handler
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG if cls.DEBUG else logging.INFO)
            ch.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            logger.addHandler(ch)

            # File handler
            logfile_path = os.path.join(cls.LOG_DIR, cls.LOG_FILENAME)
            try:
                fh = logging.FileHandler(logfile_path, encoding="utf-8")
                fh.setLevel(logging.DEBUG)
                fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
                logger.addHandler(fh)
            except Exception as e:
                # fallback: print warning and continue with console only
                print(f"[Worker WARNING] Could not create file log handler: {e}")

        cls._logger = logger
        cls._logger_initialized = True
        cls._log(f"Logger initialized. Log file: {os.path.join(cls.LOG_DIR, cls.LOG_FILENAME)}", "info")
    
    @classmethod
    def _sleep_interruptible(cls, seconds):
        """Sleep for the given seconds, but allow interruption."""
        for _ in range(seconds):
            if getattr(cls, "stop_event", None) and cls.stop_event.is_set():
                break
            time.sleep(1)

    @classmethod
    def _log(cls, message: str, level: str = "debug") -> None:
        cls._init_logger()
        if cls.DEBUG:
            print(f"[Worker DEBUG] {message}")
        if cls._logger:
            if level == "debug":
                cls._logger.debug(message)
            elif level == "info":
                cls._logger.info(message)
            elif level == "warning":
                cls._logger.warning(message)
            elif level == "error":
                cls._logger.error(message)
            else:
                cls._logger.debug(message)

    # ---------------- env account loader (called once at start) ----------------
    @classmethod
    def _load_accounts_from_env_once(cls) -> List[Dict[str, str]]:
        """
        Read environment variables EMAIL_ADDRESS_<token> and EMAIL_PASSWORD_<token>.
        Called once in start() to populate EMAIL_ACCOUNTS.
        """
        env = os.environ
        prefix = cls.ADDRESS_ENV_PREFIX
        pw_prefix = cls.PASSWORD_ENV_PREFIX

        accounts: List[Dict[str, str]] = []
        tokens_seen = []

        pat = re.compile(rf"^{re.escape(prefix)}(.+)$")
        for key in env.keys():
            m = pat.match(key)
            if not m:
                continue
            token = m.group(1)
            if token in tokens_seen:
                continue
            tokens_seen.append(token)

            addr_key = f"{prefix}{token}"
            pw_key = f"{pw_prefix}{token}"
            address = env.get(addr_key)
            password = env.get(pw_key)

            if not address:
                cls._log(f"Found {addr_key} but value empty -> skipping.", "warning")
                continue
            if not password:
                cls._log(f"Found {addr_key} but missing {pw_key} -> skipping this account.", "warning")
                continue

            accounts.append({"address": address, "password": password})

        # stable sort: try numeric token order if possible
        try:
            def _token_key(acc: Dict[str,str]) -> Any:
                for k, v in env.items():
                    if v == acc["address"] and k.startswith(prefix):
                        tok = k[len(prefix):]
                        try:
                            return int(tok)
                        except Exception:
                            return tok
                return acc["address"]
            accounts.sort(key=_token_key)
        except Exception:
            pass

        cls._log(f"Loaded {len(accounts)} account(s) ONCE from environment.", "info")
        return accounts

    # ---------------- public API ----------------
    @classmethod
    def start(cls) -> None:
        """
        Start the background worker loop. Loads EMAIL_ACCOUNTS ONCE at start.
        Safe to call multiple times; subsequent calls are no-ops while running.
        """
        with cls._running_lock:
            if cls._thread and cls._thread.is_alive():
                cls._log("Worker.start() called but worker already running.", "info")
                return

            cls._init_logger()
            cls.EMAIL_ACCOUNTS = cls._load_accounts_from_env_once()
            cls._stop_event.clear()
            cls._thread = threading.Thread(target=cls._run_loop, name="WorkerMainThread", daemon=True)
            cls._thread.start()
            cls._log("Worker background thread started.", "info")

    @classmethod
    def reload_accounts(cls) -> None:
        """
        Manually reload accounts from environment (call only if env vars changed at runtime).
        """
        cls._log("Manual reload_accounts() called.", "info")
        cls.EMAIL_ACCOUNTS = cls._load_accounts_from_env_once()

    @classmethod
    def stop(cls, join: bool = True, timeout: Optional[float] = None) -> None:
        """
        Stop the background worker gracefully.
        """
        cls._log("Worker.stop() called. Signalling stop event.", "info")
        cls._stop_event.set()
        if join and cls._thread:
            cls._thread.join(timeout=timeout)
            cls._log("Worker background thread stopped.", "info")

    @classmethod
    def add_task(cls, task: Dict[str, Any]) -> None:
        """
        Add a task to the queue.

        For send:
          {"email": "...", "email_type": "send", "instagram": "..."}

        For reply (required extra fields):
          {"email": "...", "email_type": "reply", "instagram": "...",
           "original_email_id": "<message-id>", "sheet_name": "<sheet-name>"}
        """
        if not isinstance(task, dict):
            cls._log(f"add_task: task not dict: {task}", "error")
            raise ValueError("task must be a dict")

        required = {"email", "email_type", "instagram"}
        if not required.issubset(task.keys()):
            cls._log(f"add_task: missing keys in task: {task}. Required: {required}", "error")
            raise ValueError(f"task must contain keys: {required}")

        etype = task.get("email_type")
        if etype == "reply":
            if "original_email_id" not in task or "sheet_name" not in task:
                cls._log(f"add_task: 'reply' tasks must include 'original_email_id' and 'sheet_name'. Task: {task}", "error")
                raise ValueError("reply tasks must include 'original_email_id' and 'sheet_name'")

        with cls._task_lock:
            cls._emails_to_send.append(task.copy())
            cls._log(f"Task added: {task}", "info")

    # ---------------- internal run loop ----------------
    @classmethod
    def _run_loop(cls) -> None:
        cls._log("Worker main loop entering run state.", "info")
        while not cls._stop_event.is_set():
            try:
                accounts = cls.EMAIL_ACCOUNTS
                accounts_count = len(accounts)

                with cls._task_lock:
                    tasks_count = len(cls._emails_to_send)

                if tasks_count == 0:
                    cls._log(f"No tasks to process. Sleeping for {cls.EMPTY_LIST_INTERVAL} seconds.", "info")
                    cls._sleep_interruptible(cls.EMPTY_LIST_INTERVAL)
                    continue

                if accounts_count == 0:
                    cls._log("Tasks queued but no email accounts loaded at startup. Cannot process tasks.", "error")
                    cls._sleep_interruptible(cls.EMPTY_LIST_INTERVAL)
                    continue

                cls._log(f"Starting batch: {tasks_count} queued, {accounts_count} accounts available.", "info")

                # assign up to one task per account (FIFO)
                k = accounts_count
                assigned: List[Optional[Dict[str, Any]]] = []
                with cls._task_lock:
                    for _ in range(k):
                        if cls._emails_to_send:
                            assigned.append(cls._emails_to_send.pop(0))
                        else:
                            assigned.append(None)

                # spawn one thread per account
                threads: List[threading.Thread] = []
                for account, task in zip(accounts, assigned):
                    t = threading.Thread(target=cls._per_account_worker, args=(account, task), daemon=False)
                    t.start()
                    threads.append(t)
                    cls._log(f"Spawned thread for account {account.get('address')} (task assigned: {'yes' if task else 'no'})", "debug")

                # wait for threads to finish; join with small timeouts to respond to stop event
                for t in threads:
                    while t.is_alive():
                        t.join(timeout=0.5)
                        if cls._stop_event.is_set():
                            cls._log("Stop event detected while waiting for worker threads. Breaking joins.", "warning")
                            break

                cls._log(f"Batch completed. Sleeping for {cls.INTERVAL_SECONDS} seconds.", "info")
                cls._sleep_interruptible(cls.INTERVAL_SECONDS)

            except Exception as e:
                cls._log(f"Unhandled exception in worker loop: {e}", "error")
                if cls._logger:
                    cls._logger.exception("Exception in Worker._run_loop")
                cls._sleep_interruptible(5)

        cls._log("Worker main loop exiting due to stop event.", "info")

    # ---------------- per-account worker ----------------
    @classmethod
    def _per_account_worker(cls, account: Dict[str, str], task: Optional[Dict[str, Any]]) -> None:
        addr = account.get("address", "<unknown>")
        try:
            if task is None:
                cls._log(f"[{addr}] No task assigned this cycle. Exiting thread.", "debug")
                return

            cls._log(f"[{addr}] Processing task -> recipient: {task.get('email')} (type: {task.get('email_type')})", "info")
            try:
                etype = task.get("email_type")
                if etype == "send":
                    cls._email_send(task, account)
                elif etype == "reply":
                    original_id = task.get("original_email_id")
                    sheet_name = task.get("sheet_name")
                    cls._email_reply(task, account, original_email_id=original_id, sheet_name=sheet_name)
                else:
                    cls._log(f"[{addr}] Unknown email_type '{etype}' in task {task}", "warning")
            except Exception as task_exc:
                cls._log(f"[{addr}] Exception during task {task}: {task_exc}", "error")
                if cls._logger:
                    cls._logger.exception("Exception in _per_account_worker task")
        finally:
            cls._log(f"[{addr}] Thread finished.", "debug")

    # ---------------- placeholders for actual send/reply logic ----------------
@classmethod
def _email_send(cls, task: Dict[str, Any], account: Dict[str, str]) -> None:
    cls._log(f"[{account['address']}] Sending email to {task['email']}", "info")
    try:
        msg = EmailMessage()
        msg['From'] = account['address']
        msg['To'] = task['email']
        msg['Subject'] = "Instagram Link"
        msg.set_content(f"Hello! Check this Instagram link: {task['instagram']}")

        smtp_host = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", 587))

        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            smtp.starttls()
            smtp.login(account['address'], account['password'])
            smtp.send_message(msg)

        cls._log(f"[{account['address']}] Email sent to {task['email']}", "info")
    except Exception as e:
        cls._log(f"[{account['address']}] Failed to send email: {e}", "error")

@classmethod
def _email_reply(cls, task: Dict[str, Any], account: Dict[str, str], original_email_id: str, sheet_name: str) -> None:
    cls._log(f"[{account['address']}] Replying to {task['email']}", "info")
    try:
        msg = EmailMessage()
        msg['From'] = account['address']
        msg['To'] = task['email']
        msg['Subject'] = "Re: Instagram Link"
        msg['In-Reply-To'] = original_email_id
        msg['References'] = original_email_id
        msg.set_content(f"Hello! This is a reply. Instagram link: {task['instagram']}")

        smtp_host = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", 587))

        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            smtp.starttls()
            smtp.login(account['address'], account['password'])
            smtp.send_message(msg)

        cls._log(f"[{account['address']}] Reply sent to {task['email']}", "info")
    except Exception as e:
        cls._log(f"[{account['address']}] Reply failed: {e}", "error")
    # ---------------- utility ----------------
    @classmethod
    def _sleep_interruptible(cls, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end and not cls._stop_event.is_set():
            time.sleep(0.5)


# ---------------- example main ----------------
if __name__ == "__main__":
    Worker.start()

    # send example
    Worker.add_task({"email": "user1@example.com", "email_type": "send", "instagram": "https://instagram.com/user1"})

    # reply example (requires original_email_id and sheet_name)
    Worker.add_task({
        "email": "user2@example.com",
        "email_type": "reply",
        "instagram": "https://instagram.com/user2",
        "original_email_id": "<original-message-id@example.com>",
        "sheet_name": "RepliesSheet"
    })

    # more tasks
    Worker.add_task({"email": "user3@example.com", "email_type": "send", "instagram": "https://instagram.com/user3"})
    Worker.add_task({"email": "user4@example.com", "email_type": "send", "instagram": "https://instagram.com/user4"})

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("KeyboardInterrupt -> stopping Worker...")
        Worker.stop()

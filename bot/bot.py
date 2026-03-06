import contextlib
import enum
import logging
import random
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

from .ghost_logger import GhostLogger


class DefaultLinksEnum(enum.Enum):
    HOME = "https://www.reddit.com/"
    LOGIN = "https://www.reddit.com/login/"


class Timeouts:
    @staticmethod
    def srt() -> None:
        """Short timeout (0-3s)"""
        time.sleep(random.random() + random.randint(0, 2))

    @staticmethod
    def med() -> None:
        """Medium timeout (2-6s)"""
        time.sleep(random.random() + random.randint(2, 5))

    @staticmethod
    def lng() -> None:
        """Long timeout (5-11s)"""
        time.sleep(random.random() + random.randint(5, 10))


class RedditBot:
    def __init__(self, verbose: bool = False):
        self.logger = GhostLogger()
        if verbose:
            self.logger = logging.getLogger(__name__)
            self.logger.setLevel(logging.INFO)
            self.logger.addHandler(logging.StreamHandler())
            formatter = logging.Formatter(
                "\033[93m[INFO]\033[0m %(asctime)s \033[95m%(message)s\033[0m"
            )
            self.logger.handlers[0].setFormatter(formatter)

        self.logger.info("Booting up webdriver")
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--lang=en")
        chrome_options.add_experimental_option(
            "prefs", {"profile.default_content_setting_values.notifications": 2}
        )

        service = Service(ChromeDriverManager().install())
        self.dv = webdriver.Chrome(service=service, options=chrome_options)
        self.logger.info("Webdriver booted up")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.dispose()
        return False

    def login(self, username: str, password: str):
        self.logout()

        self.logger.info(f"Logging in as {username}")
        self.dv.get(DefaultLinksEnum.LOGIN.value)

        # username
        try:
            username_field = self.dv.find_element(By.NAME, "username")
        except NoSuchElementException:
            WebDriverWait(self.dv, 20).until(
                EC.frame_to_be_available_and_switch_to_it(
                    (By.CSS_SELECTOR, "iframe[src*='login']")
                )
            )
            username_field = self.dv.find_element(By.NAME, "username")

        for ch in username:
            username_field.send_keys(ch)
            Timeouts.srt()
        Timeouts.med()

        # password
        password_field = self.dv.find_element(By.NAME, "password")

        for ch in password:
            password_field.send_keys(ch)
            Timeouts.srt()
        Timeouts.med()

        # sign in
        with contextlib.suppress(Exception):
            password_field.send_keys(Keys.ENTER)
        Timeouts.med()

        if "login" in self.dv.current_url:
            raise RuntimeError(f"Login failed for user: {username}")

        self._popup_handler()
        self._cookies_handler()
        self.logger.info("Logged in successfully.")

    def logout(self) -> None:
        self.logger.info("Clearing browser data")
        self.dv.delete_all_cookies()
        self.dv.execute_script("window.localStorage.clear();")
        self.dv.execute_script("window.sessionStorage.clear();")

    def vote(self, link: str, action: bool) -> None:
        """Vote on a post. action: True=upvote, False=downvote."""
        vote_type = "Upvoting" if action else "Downvoting"
        self.logger.info(f"{vote_type} {link}")

        self._get_link(link, handle_nsfw=True)

        # Try aria-label based selectors first, fall back to positional XPath
        label = "upvote" if action else "downvote"
        try:
            button = self.dv.find_element(
                By.CSS_SELECTOR, f"button[aria-label='{label}']"
            )
        except NoSuchElementException:
            index = 1 if action else 2
            button = self.dv.find_element(By.XPATH,
                f"/html/body/div[1]/div/div[2]/div[2]/div/div/div/div[2]/div[3]/div[1]/div[3]/div[1]/div/div[1]/div/button[{index}]"
            )

        button.click()
        Timeouts.med()

    def comment(self, link: str, text: str) -> None:
        """Post a comment on a post."""
        if not text:
            return

        self.logger.info(f"Commenting on {link}")
        self._get_link(link, handle_nsfw=True)

        html_body = self.dv.find_element(By.TAG_NAME, "body")
        html_body.send_keys(Keys.PAGE_DOWN)
        Timeouts.srt()

        # Find the comment textbox
        textbox = self._find_element_with_fallbacks(
            (By.CSS_SELECTOR, "div[contenteditable='true'][role='textbox']"),
            (By.XPATH, "/html/body/div[1]/div/div[2]/div[3]/div/div/div/div[2]/div[1]/div[2]/div[3]/div[2]/div/div/div[2]/div/div[1]/div/div/div"),
            (By.XPATH, '//*[@id="AppRouter-main-content"]/div/div/div[2]/div[3]/div[1]/div[2]/div[3]/div[2]/div/div/div[2]/div/div[1]/div/div/div'),
        )
        textbox.click()

        for ch in text:
            textbox.send_keys(ch)
            Timeouts.srt()

        # Find the submit button
        submit_btn = self._find_element_with_fallbacks(
            (By.CSS_SELECTOR, "button[type='submit'][slot='submit-button']"),
            (By.XPATH, "/html/body/div[1]/div/div[2]/div[3]/div/div/div/div[2]/div[1]/div[2]/div[3]/div[2]/div/div/div[3]/div[1]/button"),
            (By.XPATH, '//*[@id="AppRouter-main-content"]/div/div/div[2]/div[3]/div[1]/div[2]/div[3]/div[2]/div/div/div[3]/div[1]/button'),
        )
        submit_btn.click()
        Timeouts.med()

    def join_community(self, link: str, join: bool) -> None:
        """Join or leave a community. join: True=join, False=leave."""
        action_label = "Joining" if join else "Leaving"
        self.logger.info(f"{action_label} {link}")

        self._get_link(link, handle_nsfw=True)

        join_button = self._find_element_with_fallbacks(
            (By.CSS_SELECTOR, "button[id*='join-button']"),
            (By.XPATH, "/html/body/div[1]/div/div[2]/div[2]/div/div/div/div[2]/div[1]/div/div[1]/div/div[2]/div/button"),
            (By.XPATH, '//*[@id="AppRouter-main-content"]/div/div/div[2]/div[1]/div/div[1]/div/div[2]/div/button'),
        )

        button_text = join_button.text.lower()

        if (join and button_text == "join") or (not join and button_text == "joined"):
            join_button.click()
        Timeouts.med()

    def dispose(self) -> None:
        """Shut down the webdriver."""
        self.logger.info("Disposing webdriver")
        self.dv.quit()

    def _find_element_with_fallbacks(self, *locators):
        """Try multiple locator strategies, return the first match."""
        for locator in locators[:-1]:
            try:
                return self.dv.find_element(*locator)
            except NoSuchElementException:
                continue
        # Last one raises if not found
        return self.dv.find_element(*locators[-1])

    def _get_link(self, link: str, handle_nsfw: bool = False) -> None:
        self.dv.get(link)
        Timeouts.med()

        if handle_nsfw:
            with contextlib.suppress(NoSuchElementException):
                nsfw_button = self.dv.find_element(
                    By.CSS_SELECTOR, "button.nsfw-gate-btn, button[name='over18']"
                )
                nsfw_button.click()
                Timeouts.srt()

            # Fallback to absolute XPath if CSS selector didn't match
            with contextlib.suppress(NoSuchElementException):
                nsfw_button = self.dv.find_element(By.XPATH,
                    "/html/body/div[1]/div/div[2]/div[2]/div/div/div[1]/div/div/div[2]/button"
                )
                nsfw_button.click()
            Timeouts.med()

    def _popup_handler(self) -> None:
        with contextlib.suppress(NoSuchElementException):
            close_button = self.dv.find_element(
                By.CSS_SELECTOR, "button[aria-label='Close']"
            )
            close_button.click()

        # Fallback to absolute XPath
        with contextlib.suppress(NoSuchElementException):
            close_button = self.dv.find_element(By.XPATH,
                "/html/body/div[1]/div/div[2]/div[1]/header/div/div[2]/div[2]/div/div[1]/span[2]/div/div[2]/button"
            )
            close_button.click()

    def _cookies_handler(self) -> None:
        with contextlib.suppress(NoSuchElementException):
            accept_button = self.dv.find_element(
                By.CSS_SELECTOR, "button[name='accept']"
            )
            accept_button.click()

        # Fallback to absolute XPath
        with contextlib.suppress(NoSuchElementException):
            accept_button = self.dv.find_element(By.XPATH,
                "/html/body/div[1]/div/div/div/div[3]/div/form/div/button"
            )
            accept_button.click()

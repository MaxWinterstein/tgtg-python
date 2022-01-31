import datetime
import random
from http import HTTPStatus
from time import sleep
from urllib.parse import urljoin

import requests

from .exceptions import TgtgAPIError, TgtgLoginError

BASE_URL = "https://apptoogoodtogo.com/api/"
API_ITEM_ENDPOINT = "item/v7/"
LOGIN_ENDPOINT = "auth/v3/authByEmail"
AUTH_ENDPOINT = "auth/v3/authByRequestPollingId"
SIGNUP_BY_EMAIL_ENDPOINT = "auth/v2/signUpByEmail"
REFRESH_ENDPOINT = "auth/v1/token/refresh"
ALL_BUSINESS_ENDPOINT = "map/v1/listAllBusinessMap"
USER_AGENTS = [
    "TGTG/21.9.3 Dalvik/2.1.0 (Linux; U; Android 6.0.1; Nexus 5 Build/M4B30Z)",
    "TGTG/21.9.3 Dalvik/2.1.0 (Linux; U; Android 7.0; SM-G935F Build/NRD90M)",
    "TGTG/21.9.3 Dalvik/2.1.0 (Linux; Android 6.0.1; SM-G920V Build/MMB29K)",
]
DEFAULT_ACCESS_TOKEN_LIFETIME = 3600 * 4  # 4 hours


class TgtgClient:
    def __init__(
        self,
        url=BASE_URL,
        email=None,
        password=None,
        access_token=None,
        user_id=None,
        user_agent=None,
        language="en-UK",
        proxies=None,
        timeout=None,
        refresh_token=None,
        last_time_token_refreshed=None,
        access_token_lifetime=DEFAULT_ACCESS_TOKEN_LIFETIME,
        store_function=None,
    ):
        self.base_url = url

        self.email = email
        self.password = password
        if self.password:
            raise DeprecationWarning("'password' is deprecated, use 'email' only ")

        self.access_token = access_token
        self.refresh_token = refresh_token
        self.last_time_token_refreshed = last_time_token_refreshed
        self.access_token_lifetime = access_token_lifetime

        self.user_id = user_id
        self.user_agent = user_agent if user_agent else random.choice(USER_AGENTS)
        self.language = language
        self.proxies = proxies
        self.timeout = timeout

        self.store_function = store_function

    def _get_url(self, path):
        return urljoin(self.base_url, path)

    @property
    def _headers(self):
        headers = {
            "user-agent": self.user_agent,
            "accept-language": self.language,
            "Accept-Encoding": "gzip",
        }
        if self.access_token:
            headers["authorization"] = f"Bearer {self.access_token}"
        return headers

    @property
    def _already_logged(self):
        return bool(self.access_token and self.user_id)

    def _refresh_token(self):
        if (
            self.last_time_token_refreshed
            and (datetime.datetime.now() - self.last_time_token_refreshed).seconds
            <= self.access_token_lifetime
        ):
            return

        response = requests.post(
            self._get_url(REFRESH_ENDPOINT),
            headers=self._headers,
            json={"refresh_token": self.refresh_token},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            print(response.json())
            self.access_token = response.json()["access_token"]
            self.refresh_token = response.json()["refresh_token"]
            self.last_time_token_refreshed = datetime.datetime.now()

            if self.store_function:
                self.store_function(
                    access_token=self.access_token,
                    refresh_token=self.refresh_token,
                    user_id=self.user_id,
                    last_time_token_refreshed=self.last_time_token_refreshed,
                )
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def _login(self):
        if self._already_logged:
            self._refresh_token()
        else:
            if not self.access_token and not self.email:
                raise ValueError("You must fill email")

            # Step 1, request two factor mail
            response = requests.post(
                self._get_url(LOGIN_ENDPOINT),
                headers=self._headers,
                json={
                    "device_type": "ANDROID",
                    "email": self.email,
                },
                proxies=self.proxies,
                timeout=self.timeout,
            )
            if response.status_code == HTTPStatus.OK:
                login_response = response.json()

            else:
                raise TgtgLoginError(response.status_code, response.content)

            # Step 2, request periodically check if link has been clicked
            retries = 60
            while retries > 0:
                response = requests.post(
                    self._get_url(AUTH_ENDPOINT),
                    headers=self._headers,
                    json={
                        "device_type": "ANDROID",
                        "email": self.email,
                        "request_polling_id": login_response["polling_id"],
                    },
                    proxies=self.proxies,
                    timeout=self.timeout,
                )
                if response.status_code == HTTPStatus.OK:
                    login_response = response.json()
                    self.access_token = login_response["access_token"]
                    self.refresh_token = login_response["refresh_token"]
                    self.last_time_token_refreshed = datetime.datetime.now()
                    self.user_id = login_response["startup_data"]["user"]["user_id"]

                    if self.store_function:
                        self.store_function(
                            access_token=self.access_token,
                            refresh_token=self.refresh_token,
                            user_id=self.user_id,
                            last_time_token_refreshed=self.last_time_token_refreshed,
                        )

                    break
                elif response.status_code == HTTPStatus.ACCEPTED:
                    print("Login request not yet accepted. Check mail.")
                    sleep(10)
                    retries -= 1
                else:
                    raise TgtgLoginError(response.status_code, response.content)

    def get_items(
        self,
        *,
        latitude=0.0,
        longitude=0.0,
        radius=21,
        page_size=20,
        page=1,
        discover=False,
        favorites_only=True,
        item_categories=None,
        diet_categories=None,
        pickup_earliest=None,
        pickup_latest=None,
        search_phrase=None,
        with_stock_only=False,
        hidden_only=False,
        we_care_only=False,
    ):
        self._login()

        # fields are sorted like in the app
        data = {
            "user_id": self.user_id,
            "origin": {"latitude": latitude, "longitude": longitude},
            "radius": radius,
            "page_size": page_size,
            "page": page,
            "discover": discover,
            "favorites_only": favorites_only,
            "item_categories": item_categories if item_categories else [],
            "diet_categories": diet_categories if diet_categories else [],
            "pickup_earliest": pickup_earliest,
            "pickup_latest": pickup_latest,
            "search_phrase": search_phrase if search_phrase else None,
            "with_stock_only": with_stock_only,
            "hidden_only": hidden_only,
            "we_care_only": we_care_only,
        }
        response = requests.post(
            self._get_url(API_ITEM_ENDPOINT),
            headers=self._headers,
            json=data,
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            return response.json()["items"]
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def get_item(self, item_id):
        self._login()
        response = requests.post(
            urljoin(self._get_url(API_ITEM_ENDPOINT), str(item_id)),
            headers=self._headers,
            json={"user_id": self.user_id, "origin": None},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            return response.json()
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def set_favorite(self, item_id, is_favorite):
        self._login()
        response = requests.post(
            urljoin(self._get_url(API_ITEM_ENDPOINT), f"{item_id}/setFavorite"),
            headers=self._headers,
            json={"is_favorite": is_favorite},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code != HTTPStatus.OK:
            raise TgtgAPIError(response.status_code, response.content)

    def signup_by_email(
        self,
        *,
        email,
        password,
        name,
        country_id="GB",
        device_type="ANDROID",
        newsletter_opt_in=False,
        push_notification_opt_in=True,
    ):
        response = requests.post(
            self._get_url(SIGNUP_BY_EMAIL_ENDPOINT),
            headers=self._headers,
            json={
                "country_id": country_id,
                "device_type": device_type,
                "email": email,
                "name": name,
                "newsletter_opt_in": newsletter_opt_in,
                "password": password,
                "push_notification_opt_in": push_notification_opt_in,
            },
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            self.access_token = response.json()["access_token"]
            self.refresh_token = response.json()["refresh_token"]
            self.last_time_token_refreshed = datetime.datetime.now()
            self.user_id = response.json()["startup_data"]["user"]["user_id"]
            return self
        else:
            raise TgtgAPIError(response.status_code, response.content)

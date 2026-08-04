"""Adds config flow for Akuvox."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

import voluptuous as vol
from .api import AkuvoxApiClient
from .coordinator import AkuvoxDataUpdateCoordinator

from .const import (
    DOMAIN,
    DEFAULT_TOKEN,
    DEFAULT_APP_TOKEN,
    DEFAULT_REFRESH_TOKEN,
    LOGGER,
    LOCATIONS_DICT,
    COUNTRY_PHONE,
    SUBDOMAINS_LIST,
)
from .helpers import AkuvoxHelpers

helpers = AkuvoxHelpers()

class AkuvoxFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Akuvox."""

    VERSION = 1
    data: dict = {}
    rest_server_data: dict = {}
    akuvox_api_client: AkuvoxApiClient = None  # type: ignore

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return AkuvoxOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Step 0: User selects sign-in method."""

        # Initialize the API client
        if self.akuvox_api_client is None:
            coordinator: AkuvoxDataUpdateCoordinator = None # type: ignore
            if DOMAIN in self.hass.data:
                for _key, value in self.hass.data[DOMAIN].items():
                    coordinator = value
            if coordinator:
                self.akuvox_api_client = coordinator.client
            else:
                self.akuvox_api_client = AkuvoxApiClient(
                    session=async_get_clientsession(self.hass),
                    hass=self.hass,
                    entry=None)

        sign_in_options = [
            selector.SelectOptionDict(value="sms", label="1. SMS Verification (Recommended)"),
            selector.SelectOptionDict(value="app_tokens", label="2. App Tokens (Advanced)"),
            selector.SelectOptionDict(value="family_tokens", label="3. Family Member Email + passwd token"),
        ]
        data_schema = vol.Schema({
            vol.Required(
                "sign_in_method",
                default=(user_input or {}).get("sign_in_method", "sms"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=sign_in_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=False,
                )
            )
        })

        if user_input is not None:
            selection = user_input.get("sign_in_method")
            if selection == "sms":
                return await self.async_step_sms_sign_in_warning()
            if selection == "app_tokens":
                return await self.async_step_app_tokens_sign_in()
            if selection == "family_tokens":
                return await self.async_step_family_member_sign_in()

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            description_placeholders=user_input,
            last_step=False,
        )

    async def async_step_sms_sign_in_warning(self, user_input=None):
        """Step 1a: Warning before continuing with login via SMS Verification."""
        errors = {}
        sms_sign_in = "Continue sign-in via SMS Verification"
        app_tokens_sign_in = "Sign-in via app tokens"
        family_member_sign_in = "Sign-in via family member email + passwd token"
        data_schema = {
            "warning_option_selection": selector.selector({
                "select": {
                    "options": [sms_sign_in, app_tokens_sign_in, family_member_sign_in],
                }
            })
        }
        if user_input is not None:
            if "warning_option_selection" in user_input:
                selection = user_input["warning_option_selection"]
                if selection == sms_sign_in:
                    return self.async_show_form(
                        step_id="sms_sign_in",
                        data_schema=vol.Schema(self.get_sms_sign_in_schema(user_input)),
                        description_placeholders=user_input,
                        last_step=False,
                        errors=None
                    )
                if selection == app_tokens_sign_in:
                    return self.async_show_form(
                        step_id="app_tokens_sign_in",
                        data_schema=vol.Schema(self.get_app_tokens_sign_in_schema(user_input)),
                        description_placeholders=user_input,
                        last_step=False,
                        errors=None
                    )
                if selection == family_member_sign_in:
                    return self.async_show_form(
                        step_id="family_member_sign_in",
                        data_schema=vol.Schema(self.get_family_member_sign_in_schema(user_input)),
                        description_placeholders=user_input,
                        last_step=False,
                        errors=None
                    )
                errors["base"] = "Please choose a sign-in option."
            else:
                errors["base"] = "Please choose a valid sign-in option."

        return self.async_show_form(
            step_id="sms_sign_in_warning",
            data_schema=vol.Schema(data_schema),
            description_placeholders=user_input,
            last_step=False,
            errors=errors
        )


    async def async_step_sms_sign_in(self, user_input=None):
        """Step 1b: User enters their mobile phone country code and number.

        Args:
            user_input (dict): User-provided input data.

        Returns:
            dict: A dictionary representing the next step or an entry creation.

        """

        data_schema = self.get_sms_sign_in_schema(user_input)

        if user_input is not None:
            country_code = helpers.get_country_phone_code_from_name(user_input.get("country_code"))
            phone_number = user_input.get(
                "phone_number", "").replace("-", "").replace(" ", "")
            subdomain: str = user_input.get("subdomain", "Default")
            subdomain = subdomain if subdomain != "Default" else helpers.get_subdomain_from_country_code(country_code)

            location_dict = helpers.get_location_dict(country_code)
            LOGGER.debug("User will use the API subdomain '%s' for %s", subdomain, location_dict.get("country"))

            self.data = {
                "full_phone_number": f"(+{country_code}) {phone_number}",
                "country_code": country_code,
                "phone_number": phone_number,
                "subdomain": subdomain
            }

            if len(country_code) > 0 and len(phone_number) > 0: # type: ignore
                # Request SMS code for login
                request_sms_code = await self.akuvox_api_client.async_send_sms(self.hass, country_code, phone_number, subdomain)
                if request_sms_code:
                    return await self.async_step_verify_sms_code()
                else:
                    return self.async_show_form(
                        step_id="sms_sign_in",
                        data_schema=vol.Schema(data_schema),
                        description_placeholders=user_input,
                        last_step=False,
                        errors={
                            "base": "SMS code request failed. Check your phone number."
                        }
                    )

            return self.async_show_form(
                step_id="sms_sign_in",
                data_schema=vol.Schema(data_schema),
                description_placeholders=user_input,
                last_step=False,
                errors={
                    "base": "Please enter a valid country code and phone number."
                }
            )

        return self.async_show_form(
            step_id="sms_sign_in",
            data_schema=vol.Schema(data_schema),
            description_placeholders=user_input,
            last_step=False,
        )


    async def async_step_app_tokens_sign_in(self, user_input=None):
        """Step 1c: User enters app tokens and phone number to sign in."""
        data_schema = self.get_app_tokens_sign_in_schema(user_input) # type: ignore
        if user_input is not None:
            country_code: str = helpers.get_country_phone_code_from_name(user_input.get("country_code")) # type: ignore
            phone_number: str = user_input.get(
                "phone_number", "").replace("-", "").replace(" ", "")
            token: str = user_input.get("token", "")
            auth_token: str = user_input.get("auth_token", "")
            refresh_token: str = user_input.get("refresh_token", "")
            subdomain: str = user_input.get("subdomain", "Default")
            subdomain = subdomain if subdomain != "Default" else helpers.get_subdomain_from_country_code(country_code)

            self.data = {
                "full_phone_number": f"(+{country_code}) {phone_number}",
                "country_code": country_code,
                "phone_number": phone_number,
                "token": token,
                "auth_token": auth_token,
                "refresh_token": refresh_token,
                "refresh_on_first_login": user_input.get("refresh_on_first_login", True),
                "subdomain": subdomain
            }

            # Perform login via auth_token, token and phone number
            if all(len(value) > 0 for value in (country_code, phone_number, token, auth_token)):
                # Retrieve servers_list data.
                login_successful = await self.akuvox_api_client.async_make_servers_list_request(
                    hass=self.hass,
                    auth_token=auth_token,
                    token=token,
                    country_code=country_code,
                    phone_number=phone_number,
                    subdomain=subdomain)
                if login_successful is True:
                    captured_refresh_token = self.akuvox_api_client._data.refresh_token
                    if refresh_token:
                        self.akuvox_api_client.update_data("refresh_token", refresh_token)
                        captured_refresh_token = refresh_token

                    if not captured_refresh_token:
                        LOGGER.error("❌ No refresh token available after app-token sign-in.")
                        return self.async_show_form(
                            step_id="app_tokens_sign_in",
                            data_schema=vol.Schema(self.get_app_tokens_sign_in_schema(user_input)),
                            description_placeholders=user_input,
                            last_step=True,
                            errors={
                                "base": "A refresh_token is required for app-token sign-in because Akuvox rotates credentials. Capture it from SmartPlus and try again."
                            }
                        )

                    refresh_successful = True
                    if user_input.get("refresh_on_first_login", True):
                        refresh_successful = await self.akuvox_api_client.async_refresh_token(
                            reason="initial app-token validation"
                        )
                    if refresh_successful is not True:
                        return self.async_show_form(
                            step_id="app_tokens_sign_in",
                            data_schema=vol.Schema(self.get_app_tokens_sign_in_schema(user_input)),
                            description_placeholders=user_input,
                            last_step=True,
                            errors={
                                "base": "Token refresh failed. Capture a current token pair from SmartPlus and try again."
                            },
                        )

                    self.data["token"] = self.akuvox_api_client._data.token
                    self.data["refresh_token"] = self.akuvox_api_client._data.refresh_token

                    if not await self.akuvox_api_client.async_validate_credentials(
                        reason="initial app-token validation"
                    ):
                        return self.async_show_form(
                            step_id="app_tokens_sign_in",
                            data_schema=vol.Schema(self.get_app_tokens_sign_in_schema(user_input)),
                            description_placeholders=user_input,
                            last_step=True,
                            errors={
                                "base": "Token refresh succeeded, but Akuvox rejected the refreshed credentials. Capture a current token pair and try again."
                            },
                        )

                    await self.akuvox_api_client.async_retrieve_temp_keys_data()
                    devices_json = self.akuvox_api_client.get_devices_json()
                    self.data.update(devices_json)

                    ################################
                    ### Create integration entry ###
                    ################################
                    return self.async_create_entry(
                        title=self.akuvox_api_client.get_title(),
                        data=self.data
                    )
                else:
                    LOGGER.error("❌ Unable to retrieve user data. Check your tokens.")

                return self.async_show_form(
                    step_id="app_tokens_sign_in",
                    data_schema=vol.Schema(self.get_app_tokens_sign_in_schema(user_input)),
                    description_placeholders=user_input,
                    last_step=True,
                    errors={
                        "base": "Sign in failed. Please check the values entered and try again."
                    }
                )

            return self.async_show_form(
                step_id="app_tokens_sign_in",
                data_schema=vol.Schema(data_schema),
                description_placeholders=user_input,
                last_step=True,
                errors={
                    "base": "Please check the values enterted and try again."
                }
            )

        return self.async_show_form(
            step_id="app_tokens_sign_in",
            data_schema=vol.Schema(data_schema),
            description_placeholders=user_input,
            last_step=True,
        )

    async def async_step_family_member_sign_in(self, user_input=None):
        """Sign in using the family-member email/password login flow."""
        data_schema = self.get_family_member_sign_in_schema(user_input)
        if user_input is not None:
            email: str = user_input.get("email", "").strip()
            password: str = user_input.get("password", "")
            subdomain: str = user_input.get("subdomain", "Default")
            subdomain = subdomain if subdomain != "Default" else "ucloud"

            login_user = user_input.get("login_user", "").strip() or helpers.obfuscate_login_identifier(email)
            password_hash = helpers.get_password_hash(password)

            self.data = {
                "auth_mode": "family_member",
                "login_user": login_user,
                "password_hash": password_hash,
                "subdomain": subdomain,
            }

            if email and password:
                login_successful = await self.akuvox_api_client.async_family_member_login(
                    hass=self.hass,
                    login_user=login_user,
                    password_hash=password_hash,
                    subdomain=subdomain,
                )
                if login_successful is True:
                    refresh_successful = await self.akuvox_api_client.async_refresh_token(
                        reason="initial family-member validation"
                    )
                    if refresh_successful is not True:
                        return self.async_show_form(
                            step_id="family_member_sign_in",
                            data_schema=vol.Schema(self.get_family_member_sign_in_schema(user_input)),
                            description_placeholders=user_input,
                            last_step=True,
                            errors={
                                "base": "Family-member login succeeded but token rotation validation failed."
                            }
                        )

                    self.data["host"] = self.akuvox_api_client._data.host
                    self.data["token"] = self.akuvox_api_client._data.token
                    self.data["refresh_token"] = self.akuvox_api_client._data.refresh_token

                    await self.akuvox_api_client.async_retrieve_device_data()
                    await self.akuvox_api_client.async_retrieve_temp_keys_data()
                    devices_json = self.akuvox_api_client.get_devices_json()
                    self.data.update(devices_json)

                    return self.async_create_entry(
                        title=self.akuvox_api_client.get_title(),
                        data=self.data,
                    )

                return self.async_show_form(
                    step_id="family_member_sign_in",
                    data_schema=vol.Schema(self.get_family_member_sign_in_schema(user_input)),
                    description_placeholders=user_input,
                    last_step=True,
                    errors={
                        "base": "Sign in failed. Please check the values entered and try again."
                    }
                )

        return self.async_show_form(
            step_id="family_member_sign_in",
            data_schema=vol.Schema(data_schema),
            description_placeholders=user_input,
            last_step=True,
        )

    async def async_step_verify_sms_code(self, user_input=None):
        """Step 2: User enters the SMS code received on their phone for verifiation.

        Args:
            user_input (dict): User-provided input data.

        Returns:
            dict: A dictionary representing the next step or an entry creation.

        """

        data_schema = {
            vol.Required(
                "sms_code",
                msg=None,
                description="Enter the code from the SMS you received on your device."): str,
        }

        if user_input is not None and user_input:
            sms_code = user_input.get("sms_code")
            country_code = self.data["country_code"]
            phone_number = self.data["phone_number"]

            # Validate SMS code
            sign_in_response = await self.akuvox_api_client.async_sms_sign_in(
                phone_number,
                country_code,
                sms_code)
            if sign_in_response is True:

                devices_json = self.akuvox_api_client.get_devices_json()
                self.data.update(devices_json)

                ################################
                ### Create integration entry ###
                ################################
                return self.async_create_entry(
                    title=self.akuvox_api_client.get_title(),
                    data=self.data
                )

            user_input = None
            return self.async_show_form(
                step_id="verify_sms_code",
                data_schema=vol.Schema(data_schema),
                description_placeholders=user_input,
                last_step=True,
                errors={
                    "sms_code": "Invalid SMS code. Please enter the correct code."
                }
            )

        return self.async_show_form(
            step_id="verify_sms_code",
            data_schema=vol.Schema(data_schema),
            description_placeholders=user_input,
            last_step=True
        )

    def get_sms_sign_in_schema(self, user_input):
        """Get the schema for sms_sign_in step."""
        user_input = user_input or {}

        # List of countries
        default_country_name_code = helpers.find_country_name_code(str(COUNTRY_PHONE.get(self.hass.config.country,"")))
        default_country_name = LOCATIONS_DICT.get(default_country_name_code, {}).get("country") # type: ignore
        country_names_list:list = helpers.get_country_names_list()

        return {
            vol.Required("country_code",
                         default=default_country_name,
                         description="Your phone's international calling code prefix"):
                         selector.SelectSelector(
                             selector.SelectSelectorConfig(
                                 options=country_names_list,
                                 mode=selector.SelectSelectorMode.DROPDOWN,
                                 custom_value=False),
                                 ),
            vol.Required(
                "phone_number",
                msg=None,
                default=user_input.get("phone_number"),  # type: ignore
                description="Your phone number"): str,
            vol.Optional("subdomain",
                default="Default", # type: ignore
                description="Manually set the regional API subdomain"):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=SUBDOMAINS_LIST,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        custom_value=True),
                        )
        }

    def get_app_tokens_sign_in_schema(self, user_input: dict = {}):
        """Get the schema for app_tokens_sign_in step."""
        user_input = user_input or {}

        default_country_name_code = helpers.find_country_name_code(str(COUNTRY_PHONE.get(self.hass.config.country,"")))
        default_country_name = LOCATIONS_DICT.get(default_country_name_code, {}).get("country") # type: ignore
        country_names_list:list = helpers.get_country_names_list()

        return {
            vol.Required("country_code",
                         default=default_country_name,
                         description="Your phone's international calling code prefix"):
                         selector.SelectSelector(
                             selector.SelectSelectorConfig(
                                 options=country_names_list,
                                 mode=selector.SelectSelectorMode.DROPDOWN,
                                 custom_value=False),
                                 ),
            vol.Required(
                "phone_number",
                msg=None,
                default=user_input.get("phone_number"),  # type: ignore
                description="Your phone number"): str,
            vol.Required(
                "auth_token",
                msg=None,
                default=user_input.get("auth_token", DEFAULT_APP_TOKEN),  # type: ignore
                description="Your SmartPlus account's auth_token string"): str,
            vol.Required(
                "token",
                msg=None,
                default=user_input.get("token", DEFAULT_TOKEN),  # type: ignore
                description="Your SmartPlus account's token string"): str,
            vol.Optional(
                "refresh_token",
                msg=None,
                default=user_input.get("refresh_token", DEFAULT_REFRESH_TOKEN),  # type: ignore
                description="Optional: your SmartPlus account's refresh_token string"): str,
            vol.Optional(
                "refresh_on_first_login",
                default=user_input.get("refresh_on_first_login", True),
                description="Immediately rotate the captured token pair after sign-in (recommended)"): bool,
            vol.Optional("subdomain",
                         default="Default", # type: ignore
                         description="Manually set the regional API subdomain"):
                         selector.SelectSelector(
                             selector.SelectSelectorConfig(
                                 options=SUBDOMAINS_LIST,
                                 mode=selector.SelectSelectorMode.DROPDOWN,
                                 custom_value=True),
                                 )
        }

    def get_family_member_sign_in_schema(self, user_input: dict = {}):
        """Get the schema for family_member_sign_in step."""
        user_input = user_input or {}
        return {
            vol.Required(
                "email",
                msg=None,
                default=user_input.get("email", ""),
                description="Family-member email address",
            ): str,
            vol.Required(
                "password",
                msg=None,
                default=user_input.get("password", ""),
                description="Family-member password (hashed locally; never logged)",
            ): str,
            vol.Optional(
                "login_user",
                default=user_input.get("login_user", ""),
                description="Optional SmartPlus `user` value; leave blank to derive it from the email",
            ): str,
            vol.Optional(
                "subdomain",
                default=user_input.get("subdomain", "ucloud"),  # type: ignore
                description="Regional API subdomain",
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=SUBDOMAINS_LIST,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
        }

class AkuvoxOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Akuvox integration."""

    akuvox_api_client: AkuvoxApiClient = None  # type: ignore

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the config entry for old and current Home Assistant versions."""
        if hasattr(self, "_config_entry"):
            return self._config_entry
        return super().config_entry

    async def async_step_init(self, user_input=None):
        """Configure authentication and event behavior."""
        current_subdomain = self.get_data_key_value("subdomain", "ucloud")
        if current_subdomain == "Default":
            current_subdomain = "ucloud"
        subdomain_options = [subdomain for subdomain in SUBDOMAINS_LIST if subdomain != "Default"]
        event_screenshot_options = {
            "asap": "Receive events immediately without waiting for screenshots.",
            "wait": "Wait for camera screenshots before sending events.",
        }
        options_schema = vol.Schema({
            vol.Required(
                "auth_mode",
                default=self.get_data_key_value("auth_mode", "app_tokens"),
            ): vol.In({
                "app_tokens": "App tokens",
                "family_member": "Family-member email and password",
            }),
            vol.Optional("auth_token", default=self.get_data_key_value("auth_token", "")): str,
            vol.Optional("token", default=self.get_data_key_value("token", "")): str,
            vol.Optional("refresh_token", default=self.get_data_key_value("refresh_token", "")): str,
            vol.Optional("family_email", default=""): str,
            vol.Optional("family_password", default=""): str,
            vol.Optional("family_user", default=""): str,
            vol.Optional("refresh_and_validate", default=True): bool,
            vol.Required("subdomain", default=current_subdomain): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=subdomain_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=False,
                )
            ),
            vol.Required(
                "event_screenshot_options",
                default=self.get_data_key_value("event_screenshot_options", "asap"),
            ): vol.In(event_screenshot_options),
        })

        if user_input is None:
            return self.async_show_form(step_id="init", data_schema=options_schema)

        selected_auth_mode = user_input["auth_mode"]
        selected_subdomain = user_input["subdomain"]
        coordinator = next(iter(self.hass.data[DOMAIN].values()), None)
        if coordinator is None:
            return self.async_show_form(
                step_id="init",
                data_schema=options_schema,
                errors={"base": "Integration is not ready. Restart Home Assistant and try again."},
            )

        self.akuvox_api_client = coordinator.client
        saved_options = {
            "auth_mode": selected_auth_mode,
            "auth_token": user_input.get("auth_token", "").strip(),
            "token": user_input.get("token", "").strip(),
            "refresh_token": user_input.get("refresh_token", "").strip(),
            "subdomain": selected_subdomain,
            "event_screenshot_options": user_input["event_screenshot_options"],
            "wait_for_image_url": user_input["event_screenshot_options"] == "wait",
        }

        if selected_auth_mode == "family_member":
            family_email = user_input.get("family_email", "").strip()
            family_password = user_input.get("family_password", "")
            if not family_email or not family_password:
                return self.async_show_form(
                    step_id="init",
                    data_schema=options_schema,
                    errors={"base": "Enter the family-member email and password to re-authenticate."},
                )

            login_user = user_input.get("family_user", "").strip()
            login_user = login_user or helpers.obfuscate_login_identifier(family_email)
            password_hash = helpers.get_password_hash(family_password)
            login_successful = await self.akuvox_api_client.async_family_member_login(
                hass=self.hass,
                login_user=login_user,
                password_hash=password_hash,
                subdomain=selected_subdomain,
            )
            if not login_successful or not await self.akuvox_api_client.async_refresh_token(
                reason="family-member configuration re-authentication"
            ) or not await self.akuvox_api_client.async_validate_credentials(
                reason="family-member configuration re-authentication"
            ):
                return self.async_show_form(
                    step_id="init",
                    data_schema=options_schema,
                    errors={"base": "Family-member login failed. Check the email, password, and region."},
                )

            saved_options.update({
                "login_user": login_user,
                "password_hash": password_hash,
                "host": self.akuvox_api_client._data.host,
                "token": self.akuvox_api_client._data.token,
                "refresh_token": self.akuvox_api_client._data.refresh_token,
            })
        elif user_input.get("refresh_and_validate", True):
            if not saved_options["token"] or not saved_options["refresh_token"]:
                return self.async_show_form(
                    step_id="init",
                    data_schema=options_schema,
                    errors={"base": "Enter both an app token and refresh token before refreshing credentials."},
                )
            self.akuvox_api_client.init_api_with_data(
                hass=self.hass,
                subdomain=selected_subdomain,
                auth_mode="app_tokens",
                auth_token=saved_options["auth_token"],
                token=saved_options["token"],
                refresh_token=saved_options["refresh_token"],
                refresh_on_first_login=True,
            )
            if not await self.akuvox_api_client.async_refresh_token(reason="configuration update"):
                return self.async_show_form(
                    step_id="init",
                    data_schema=options_schema,
                    errors={"base": "Token refresh failed. Enter a current token pair or use family-member login."},
                )
            if not await self.akuvox_api_client.async_validate_credentials(
                reason="configuration update"
            ):
                return self.async_show_form(
                    step_id="init",
                    data_schema=options_schema,
                    errors={"base": "Token refresh succeeded, but the refreshed credentials could not access your Akuvox devices."},
                )
            saved_options.update({
                "token": self.akuvox_api_client._data.token,
                "refresh_token": self.akuvox_api_client._data.refresh_token,
            })

        saved_options = {
            key: value for key, value in saved_options.items() if value not in (None, "")
        }
        return self.async_create_entry(title="", data=saved_options)

    def get_data_key_value(self, key, placeholder=None):
        """Get the value for a given key. Options flow 1st, Config flow 2nd."""
        dicts = [dict(self.config_entry.options), dict(self.config_entry.data)]
        for p_dict in dicts:
            if key in p_dict:
                return p_dict[key]
        return placeholder

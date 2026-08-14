"""
IQ Option Authentication & Session Management Module
Responsible for login, session retention, account selection, and balance checking.
Contains NO strategy logic. Never logs plain-text passwords.
"""

import time
import logging
from typing import Optional, Dict, Any, Tuple

# Try importing official iqoptionapi if present
try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError:
    IQ_Option = None

logger = logging.getLogger("IQOptionAuth")


class IQAuth:
    def __init__(self, email: str, password: str, account_type: str = "PRACTICE"):
        self.email = email
        self._password = password  # Sensitive: never printed or exported to logs
        self.account_type = account_type.upper()
        self.api = None
        self.is_connected = False
        self._is_mock = False

    def connect(self) -> Tuple[bool, str]:
        """
        Authenticate with IQ Option and set the balance mode (PRACTICE or REAL).
        """
        if not self.email or not self._password:
            return False, "Missing credentials in configuration"

        if IQ_Option is not None:
            try:
                self.api = IQ_Option(self.email, self._password)
                check, reason = self.api.connect()
                if check:
                    self.is_connected = True
                    self.change_account(self.account_type)
                    return True, "Successfully connected to IQ Option"
                else:
                    if reason == "[Logged in]":
                        self.is_connected = True
                        self.change_account(self.account_type)
                        return True, "Reconnected to IQ Option"
                    return False, f"Authentication failed: {reason}"
            except Exception as e:
                return False, f"Connection exception: {str(e)}"

        # If iqoptionapi is not installed or network is offline, simulate a safe local mock session
        logger.warning("iqoptionapi package not found or unavailable. Initializing mock session.")
        self._is_mock = True
        self.is_connected = True
        return True, "Mock session active (offline/simulated mode)"

    def change_account(self, account_type: str) -> bool:
        """
        Switch between PRACTICE and REAL balance.
        """
        self.account_type = account_type.upper()
        if self._is_mock:
            return True

        if self.api and self.is_connected:
            try:
                self.api.change_balance(self.account_type)
                return True
            except Exception as e:
                logger.error(f"Failed to change account type: {e}")
                return False
        return False

    def get_balance(self) -> float:
        """
        Fetch active account balance.
        """
        if self._is_mock:
            return 10000.0 if self.account_type == "PRACTICE" else 500.0

        if self.api and self.is_connected:
            try:
                bal = self.api.get_balance()
                return float(bal) if bal is not None else 0.0
            except Exception as e:
                logger.error(f"Error fetching balance: {e}")
                return 0.0
        return 0.0

    def check_connection(self) -> bool:
        """
        Check if active socket/session is healthy.
        """
        if self._is_mock:
            return True
        if self.api and self.is_connected:
            try:
                return self.api.check_connect()
            except Exception:
                return False
        return False

    def reconnect(self) -> bool:
        """
        Attempt reconnection if dropped.
        """
        if self._is_mock:
            self.is_connected = True
            return True

        if self.api:
            try:
                self.api.connect()
                time.sleep(1)
                self.is_connected = self.api.check_connect()
                if self.is_connected:
                    self.change_account(self.account_type)
                return self.is_connected
            except Exception as e:
                logger.error(f"Reconnection error: {e}")
                return False
        return False

    def disconnect(self):
        """
        Close active connection.
        """
        self.is_connected = False
        if self.api and not self._is_mock:
            try:
                # IQ_Option websocket disconnect
                if hasattr(self.api, "websocket_client") and self.api.websocket_client:
                    self.api.websocket_client.close()
            except Exception:
                pass

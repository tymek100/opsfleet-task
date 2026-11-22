"""An accidental settings or ADC lookup must fail before reading local secrets."""

import pytest
from google import auth

from retail_agent.config import Settings


@pytest.mark.parametrize("lookup", ["settings", "adc", "credentials_file"])
def test_ambient_configuration_is_blocked_by_default(lookup):
    with pytest.raises(AssertionError, match="Offline tests"):
        if lookup == "settings":
            Settings.load()
        elif lookup == "adc":
            auth.default()
        else:
            auth.load_credentials_from_file("/unread/credentials.json")

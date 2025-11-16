from kgfoundry_common.config import AppSettings
from tests._helpers import assertions


def test_import() -> None:
    """Test that kgfoundry_common.config can be imported and instantiated."""
    settings = AppSettings()
    assertions.expect_equal(settings.log_level, "INFO")

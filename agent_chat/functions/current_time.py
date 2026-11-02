from django.utils import timezone
from langchain.tools import tool


@tool
def get_current_datetime() -> dict[str, str]:
    """Get the current date and time in ResortEase's configured local timezone."""
    current_time = timezone.localtime(timezone.now())
    return {
        "date": current_time.date().isoformat(),
        "time": current_time.strftime("%H:%M:%S"),
        "weekday": current_time.strftime("%A"),
        "timezone": timezone.get_current_timezone_name(),
        "datetime": current_time.isoformat(),
    }

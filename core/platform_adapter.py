import platform

if platform.system() == "Linux":
    from core.platform.linux import (
        calculate_cpu,
        get_memory_usage,
        get_io_wait,
        get_top_process,
    )
    PLATFORM = "Linux"

elif platform.system() == "Windows":
    from core.platform.windows import (  # type: ignore[no-redef]
        calculate_cpu,
        get_memory_usage,
        get_io_wait,
        get_top_process,
    )
    PLATFORM = "Windows"

else:
    raise Exception("Unsupported platform")

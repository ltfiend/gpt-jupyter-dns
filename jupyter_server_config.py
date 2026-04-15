# Jupyter server config — tuned for long-running DNS test cells (30min+).

# Never shut down the server due to inactivity.
c.ServerApp.shutdown_no_activity_timeout = 0

# Never cull kernels; even idle ones may be attached to a cell the user
# comes back to. `cull_busy`/`cull_connected` already default False, but
# pinning them here makes the intent explicit.
c.MappingKernelManager.cull_idle_timeout = 0
c.MappingKernelManager.cull_interval = 0
c.MappingKernelManager.cull_busy = False
c.MappingKernelManager.cull_connected = False

# Long-running cells can take a while to respond to kernel_info pings
# after startup — give them room before the client gives up.
c.MappingKernelManager.kernel_info_timeout = 600

# Don't throttle notebook output. Defaults (1MB/s, 1000 msg/s) trip on
# dnspyre/flamethrower runs that dump a lot of lines.
c.ServerApp.iopub_data_rate_limit = 1.0e12
c.ServerApp.iopub_msg_rate_limit = 100000
c.ServerApp.rate_limit_window = 10.0

# Keep the browser↔server websocket alive during silent stretches so a
# 30-minute cell doesn't lose its output stream to an idle disconnect.
c.ServerApp.tornado_settings = {
    "ws_ping_interval": 30000,   # ms
    "ws_ping_timeout": 120000,   # ms
}

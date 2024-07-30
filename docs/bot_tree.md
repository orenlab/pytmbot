## 🌲 Bot tree

```
├── Dockerfile                              - Main Dockerfile
├── LICENSE                                 - Licence file
├── README.md                               - Main README
├── SECURITY.md                             - Security policy
├── app
│   ├── __init__.py                         - Bot core
│   ├── core
│   │   ├── __init__.py                     
│   │   ├── adapters
│   │   │   ├── __init__.py
│   │   │   ├── docker_adapter.py           - Docker adapter
│   │   │   ├── podman_adapter.py           - Podman adapter (in development)
│   │   │   └── psutil_adapter.py           - Psutil adapter
│   │   ├── exceptions.py                   - Custom exceptions
│   │   ├── handlers
│   │   │   ├── __init__.py                 - Import all handlers in one list
│   │   │   ├── default_handlers
│   │   │   │   ├── __init__.py             
│   │   │   │   ├── about_bot.py            - About bot handler
│   │   │   │   ├── back_handler.py         - back to main menu handler
│   │   │   │   ├── check_bot_update.py     - Check pyTMbot updates
│   │   │   │   ├── containers_handler.py   - Container handler
│   │   │   │   ├── docker_handler.py       - Docker handler
│   │   │   │   ├── echo.py                 - Handle uncknown command
│   │   │   │   ├── fs_handler.py           - Filesystem handler
│   │   │   │   ├── images_handler.py       - Docker images handler
│   │   │   │   ├── load_avg_handler.py     - Load average handler
│   │   │   │   ├── memory_handler.py       - Memory handler
│   │   │   │   ├── net_io_stat.py          - Network handler
│   │   │   │   ├── process_handler.py      - Process handler
│   │   │   │   ├── sensors_handler.py      - Sensors handler
│   │   │   │   ├── start_handler.py        - Main, start handler
│   │   │   │   └── uptime_handlers.py      - Uptime handler
│   │   │   ├── handler.py                  - Base handler class (abc)
│   │   │   ├── handlers_aggregator.py      - Main handlers aggregator
│   │   │   └── inline_handlers
│   │   │       ├── __init__.py
│   │   │       ├── containers_full_info.py - Full containers info handler
│   │   │       └── swap_handler.py         - Swap inline handler
│   │   │       └── update_info.py          - Updates info inline handler
│   │   ├── jinja2
│   │   │   ├── __init__.py
│   │   │   └── jinja2.py                   - Main jinja2 class
│   │   ├── keyboards
│   │   │   ├── __init__.py
│   │   │   └── keyboards.py                - Main keyboards class  
│   │   ├── logs.py                         - Custom logger
│   │   ├── middleware
│   │   │   ├── __init__.py
│   │   │   └── auth.py                     - Auth middleware class
│   │   └── settings
│   │       ├── __init__.py
│   │       ├── bot_settings.py             - Class to load configuration from .pytmbotenv
│   │       ├── keyboards.py                - Keyboards settings
│   │       └── loggers.py                  - Logger templates
│   ├── main.py                             - Main bot class
│   ├── templates
│   │   ├── about_bot.jinja2                - Bot update jinja2 template
│   │   ├── bot_update.jinja2               - Bot update jinja2 template
│   │   ├── containers.jinja2               - Containers jinja2 template
│   │   ├── containers_full_info.jinja2     - Containers full info jinja2 template                    
│   │   ├── fs.jinja2                       - Filesystem jinja2 template
│   │   ├── how_update.jinja2               - Update instruction jinja2 template
│   │   ├── index.jinja2                    - Start jinja2 template
│   │   ├── load_average.jinja2             - Load average jinja2 template
│   │   ├── memory.jinja2                   - Memory jinja2 template
│   │   ├── none.jinja2                     - Docker jinja2 template
│   │   ├── process.jinja2                  - Process jinja2 template
│   │   ├── sensors.jinja2                  - Sensors jinja2 template
│   │   ├── swap.jinja2                     - Swap jinja2 template
│   │   └── uptime.jinja2                   - Uptime jinja2 template
│   └── utilities
│       ├── __init__.py
│       └── utilities.py                    - Some utility
├── bot_cli
│   ├── cfg_templates
│   │   └── env.py                          - Template for initial setup
│   └── fs.py                               - Filesystem utility
├── docker-compose.yml                      - Docker Compose file (used main Dockerfile)
├── docs
│   ├── installation.md                     - Installation guide
│   ├── roadmap.md                          - Roadmap guide
│   └── screenshots.md                      - Bots screenshot
├── hub.Dockerfile                          - Dockerfile CI/CD based on Alpine
├── poetry.lock                             - Poetry file
├── pyproject.toml                          - Poetry file
├── requirements.txt                        - Requirements for build Docker image
├── setup_bot.py                            - Initial setup bot script
├── setup_req.txt                           - Setup requirements
├── tests                                   - Bot tests
```
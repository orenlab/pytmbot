from collections import namedtuple

SessionManager = namedtuple('SessionManager', ['user_id', 'auth_process', 'last_success_auth', 'totp_attempts'],
                            defaults=[None, None, None, None])

import environ

env = environ.Env()

BASE_DIR_ENV_FILE = environ.Path(__file__) - 2

environ.Env.read_env(str(BASE_DIR_ENV_FILE.path(".env")))
